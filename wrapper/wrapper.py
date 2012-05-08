import os
import sys
import traceback
import random
import time
import select
import re
import gzip

import subprocess
from threading import Thread
from Queue import Queue, Empty

from blessings import Terminal

import ansiterm
import prompt

###
### Nerd...
###


servers_dir = '/ssd'
logs_dir = '/home/reddit/logs'
server_command = 'java -jar -Xmx2800M -Xms2800M -server -Djline.terminal=jline.UnsupportedTerminal buk.jar nogui'
output_exp = '^\d{2}:\d{2}:\d{2} \[%s\] %s'

# -XX:+UseFastAccessorMethods -XX:+UnlockExperimentalVMOptions -XX:+UseG1GC  -XX:MaxGCPauseMillis=50 -XX:UseSSE=3 -XX:+UseCompressedOops

###
### Testing
###

#servers_dir = '/home/barney/mcdev'
#logs_dir = '/home/barney/mcdev/wrapper/logs'
#server_command = 'java -Xmx1024M -Xms1024M -jar minecraft_server.jar nogui'
#output_exp = '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[%s\] %s'

lwc_exp = 'Removing corrupted protection:.*Owner=([A-Za-z0-9_]{1,16}) Location=\[([^\s]+) ([0-9-]+),([0-9-]+),([0-9-]+)\] Created='

save_interval = 600
restart_interval = 7200
message_interval = 200

hang_check_interval = 60
hang_timeout = 10
hang_fail_limit = 10 #Number of times to check if check if server is hung before rebooting it.

save_warn_delay = 30
stop_warn_delay = 60
restart_warn_delay = 60

#How long to wait for server to stop before killing via ~stop or ~restart
soft_wait = 120

class ServerInterface:
    stopping = False
    paused = False
    expecting_stop = False
    hang_fails = 0
    tasks = []
    log = ''
    def __init__(self, server_path):
        self.server_path = server_path
        self.server = None
        
        #Gives us the width
        self.term = Terminal()
        
        #Handles input nicely
        self.prompt = prompt.Prompt(self.run_command_from_prompt)
        
        #Queued server output
        self.server_output_queue = Queue()
        
        #Stuff to output (includes server output)
        self.console_output = []
        
        #Move to server directory
        os.chdir(os.path.join(servers_dir, self.server_path))
        
        #In case of any residual logs...
        self.backup()
        
        #Read random messages
        self.messages = open("messages.txt").read().splitlines()
        
        #Read triggers
        self.triggers = open("triggers.txt").read().splitlines()
        self.triggers = [x.split(",", 1) for x in self.triggers]
        
        #Start
        self.start_server()
   
    def backup(self):
        if os.path.exists('server.log'):
            d = time.strftime("%Y-%m-%d-%H:%M:%S", time.gmtime())
            new_path = os.path.join(logs_dir, self.server_path, 'server-'+d+'.log')
            os.rename('server.log', new_path)
            zipper = subprocess.call(['gzip', '-9', new_path])
            self.debug('server.log backup done!')
    
    #Saves self.log to a file in case of a wrapper failure etc.
    def emergency_backup(self):
        d = time.strftime("%Y-%m-%d-%H:%M:%S", time.gmtime())
        path = os.path.join(logs_dir, self.server_path, 'fail-'+d+'.log')
        f = open(path, 'w')
        f.write(ansiterm.strip_colors(self.log))
        f.close()
        self.log = ''
        self.debug('emergency backup done!')

    def debug(self, text):
        self.console_output.append("= "+text)

    def start_server(self):
        self.exit_on_server_stop = False
        
        #start the server...
        self.server = subprocess.Popen(server_command.split(' '),
           stdout=subprocess.PIPE,
           stderr=subprocess.PIPE,
           stdin =subprocess.PIPE,
           bufsize=1,
           close_fds = True)
        
        
        #output threads...
        def enqueue_output(out, queue, alert):
            for line in iter(out.readline, b''):
                queue.put(line.strip())
            if alert:
                queue.put(None)
            out.close()
        
        #stdout
        t = Thread(target=enqueue_output, args=(self.server.stdout, self.server_output_queue, True))
        t.daemon = True
        t.start()
        
        #stderr
        t2 = Thread(target=enqueue_output, args=(self.server.stderr, self.server_output_queue, False))
        t2.daemon = True
        t2.start()
        
        self.tasks = []
        self.add_task(restart_interval, '~delayed-soft-restart')
        self.add_task(save_interval, '~loop-save')
        self.add_task(hang_check_interval, '~hang-loop')
        self.add_task(message_interval, '~message-loop')

    def add_task(self, t, command):
        self.tasks.append((t+time.time(), command))
        self.tasks = sorted(self.tasks)
    
    def remove_task(self, command):
        removed = 0
        indices = []
        for i, t in enumerate(self.tasks):
            if t[1].endswith(command):
                indices.append(i)
                removed += 1
        
        j = 0
        for i in indices:
            self.tasks.pop(i-j)
            j += 1
        
        return removed > 0
    
    def next_restart(self):
        next = None
        for t, task in self.tasks:
            if task == '~delayed-soft-restart' and (not next or next > t):
                next = t
        
        if next:
            return next - time.time() + restart_warn_delay
        else:
            return None
                
    
    def run_forever(self):
        ansiterm.raw_mode(True)
        while not self.stopping:
            try:
                #Server tasks
                while len(self.tasks) and self.tasks[0][0] < time.time():
                    t, command = self.tasks.pop(0)
                    self.run_command(command)
                
                #Handle stdin
                prompt_updated = select.select([sys.stdin],[],[],0)[0]
                if prompt_updated:
                    try:
                        self.prompt.write(sys.stdin.read())
                    except:
                        pass
                    
                #Handle server output
                while True:
                    try: 
                        l = self.server_output_queue.get_nowait()
                        
                        #Server process stopped...
                        if l == None: 
                            self.server_stopped()
                            continue
                        
                        #Triggers
                        m = re.match(output_exp % ('INFO', '<([A-Za-z0-9_]{1,16})> \!(\w+)'), l)
                        if m:
                            user = m.group(1)
                            keyword = '!'+m.group(2)
                            for k, text in self.triggers:
                                if k == keyword:
                                    self.run_command('cmsg %s %s' % (user, text))
                            
                        #Check for server stop
                        m = re.match(output_exp % ('INFO', 'Stopping server'), l)
                        if m:
                            self.hang_fails = 0
                            #clear stop and restart tasks
                            self.remove_task('restart')
                            self.remove_task('stop')
                        
                        #Check for out-of-memory
                        m = re.match(output_exp % ('SEVERE', 'java.lang.OutOfMemoryError: GC overhead limit exceeded'), l)
                        if m:
                            self.debug('out of memory, restarting server...')
                            self.emergency_backup()
                            self.run_command('~hard-restart')
                        
                        #Check for unknown command (means the server isn't hung)
                        m = re.match(output_exp % ('INFO', 'Unknown command'), l)
                        if m:
                            self.hang_fails = 0
                            removed = self.remove_task('~hang-timeout')
                            if removed:
                                continue
                        
                        #LWC fuck-ups
                        m = re.match(output_exp % ('INFO', lwc_exp), l)
                        if m:
                            w = {'world': 'overworld', 'world_nether': 'nether', 'world_the_end': 'end'}
                            a = m.groups()
                            a = (a[0],a[2],a[3],a[4],w[a[1]])
                            t = "%s Your lwc protection at %s, %s, %s in the %s was removed! Please re-lock if this is in error." % a
                            self.run_command('cmsg '+t)
                            self.run_command('mail send '+t)
                            
                        
                        self.console_output.append(l)
                    
                    except Empty:
                        break
                
                #Write any server output
                if self.console_output:
                    self.clear_prompt()
                    for l in self.console_output:
                        sys.stdout.write(l+'\n')
                        self.log += l+'\n'
                    sys.stdout.write(str(self.prompt))
                    self.console_output = []
                
                #Write prompt
                elif prompt_updated:
                    self.clear_prompt()
                    sys.stdout.write(str(self.prompt))
                
                sys.stdout.flush()
                time.sleep(0.1)

            except KeyboardInterrupt:
                self.debug('got ctrl-c, stopping...')
                self.debug('use ~hard-stop if the server won\'t die')
                self.run_command('~stop')
            
            except Exception, e:
                for l in traceback.format_exc().strip().split('\n'):
                    self.debug(l)
                self.debug('stopping...')  
                self.emergency_backup() 
                self.run_command('~stop')

        self.clear_prompt()
        ansiterm.raw_mode(False)

    def run_command_from_prompt(self, command):
        self.console_output.append(self.prompt.prefix + self.prompt.text)
        self.run_command(command)

    def run_command(self, command):
        if command.startswith('~'):
            self.run_internal_command(command)
        elif self.server:
            try:
                self.server.stdin.write(command+'\n')
            except:
                pass
    
    def run_internal_command(self, command):
        #Save
        if command == '~save':
            if self.server:
                self.run_command('say MAP IS SAVING. PREPARE FOR A LITTLE LAG.')
                self.run_command('save-all')
        
        elif command == '~delayed-save':
            self.run_command('say SAVING IN %d SECONDS' % save_warn_delay)
            self.add_task(save_warn_delay, '~save')
        
        elif command == '~loop-save':
            self.remove_task('save')
            self.run_command('~delayed-save')
            self.add_task(save_interval, '~loop-save')
        
        #Restart
        elif command == '~restart':
            self.run_command('~soft-restart')
            self.add_task(soft_wait, '~hard-restart')
        
        elif command == '~soft-restart':
            self.expecting_stop = True
            self.run_command('~save')
            self.run_command('kickforrestart')
            self.run_command('stop')
        
        elif command == '~delayed-soft-restart':
            self.remove_task("save")
            self.run_command("say PLANNED RESTART IN %d SECONDS." % restart_warn_delay)
            self.run_command("say ALL PROGRESS WILL BE SAVED....")
            self.add_task(restart_warn_delay, '~soft-restart')

        elif command == '~hard-restart':
            self.expecting_stop = True
            if self.server:
                os.kill(self.server.pid, 9)
        
        #Stop        
        elif command == '~stop':
            self.run_command('~soft-stop')
            self.add_task(soft_wait, '~hard-stop')
        
        elif command == '~soft-stop':
            self.exit_on_server_stop = True
            self.run_command('~soft-restart')
        
        elif command == '~delayed-soft-stop':
            self.remove_task('save')
            self.run_command("say SERVER GOING DOWN FOR MAINTENANCE IN %d SECONDS." % stop_warn_delay)
            self.run_command("say ALL PROGRESS WILL BE SAVED....")
            self.add_task(stop_warn_delay, '~soft-stop')

        elif command == '~hard-stop':
            self.exit_on_server_stop = True
            self.run_command('~hard-restart')
        
        #Shows minutes til next restart
        elif command == '~next-restart':
            n = self.next_restart()
            if n:
                self.debug('next restart in %d minutes' % (n/60))
            else:
                self.debug('no restart scheduled, might be imminent?')
        
        elif command == '~emergency-backup':
            self.emergency_backup()
        
        #Check if the server is hung...
        elif command == '~hang-loop':
            self.run_command('') #Send an empty command, to generate 'unknown command'
            self.add_task(hang_check_interval, '~hang-loop')
            self.add_task(hang_timeout, '~hang-timeout')
        
        #This is run if the hang test timed out
        elif command == '~hang-timeout':
            self.hang_fails +=1
            self.debug('server failed hang check %d of %d' % (self.hang_fails, hang_fail_limit))
            if self.hang_fails >= hang_fail_limit:
                self.debug('killing hung server...')
                self.emergency_backup()
                self.hang_fails = 0
                self.run_command('~hard-restart')
        
        #Prints a random message from messages.txt
        elif command == '~message-loop':
            self.run_command('say '+self.messages[random.randint(0,len(self.messages)-1)])
            self.add_task(message_interval, '~message-loop')
        
        else:
            self.debug('unknown command')
        
    
    def server_stopped(self):
        if self.server:
            self.backup()
            if self.expecting_stop:
                if self.exit_on_server_stop:
                    self.server = None
                    self.stopping = True
                else:
                    self.start_server()
            else:
                self.debug('server stopped unexpectedly, exiting...')
                self.emergency_backup()
                self.server = None
                self.stopping = True
        
    
    def clear_prompt(self):
        sys.stdout.write('\r' + ' '*self.term.width + '\r')
        

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print "Usually started within screen. Use: ~/start survival|creative|pve"
        print "Usage: python server_wrapper.py survival|creative|pve"
        sys.exit(1)
    server = sys.argv[1]
    wrapper = ServerInterface(server)
    wrapper.run_forever()
