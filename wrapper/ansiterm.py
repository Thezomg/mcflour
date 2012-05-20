import sys
import tty
import termios
import fcntl
import os
import re

TYPE_CHAR = 1
TYPE_SPECIAL = 2

keys = {
    '\x1B[A' : 'arrow_up',
    '\x1B[B' : 'arrow_down',
    '\x1B[C' : 'arrow_right',
    '\x1B[D' : 'arrow_left',
    '\x1BOH' : 'home',
    '\x1BOF' : 'end',
    '\x1B[1~': 'home',
    '\x1B[3~': 'delete',
    '\x1B[4~': 'end'
}

old = [None, None]

def raw_mode(enable):
    fd = sys.stdin.fileno()
    if enable:
        old[0] = termios.tcgetattr(fd)
        newattr = old[0][:]
        newattr[3] = newattr[3] & ~termios.ICANON & ~termios.ECHO
        termios.tcsetattr(fd, termios.TCSANOW, newattr)
        old[1] = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, old[1] | os.O_NONBLOCK)
    else:
        termios.tcsetattr(fd, termios.TCSAFLUSH, old[0])
        fcntl.fcntl(fd, fcntl.F_SETFL, old[1])


def decode_char(s):
    if s[0] == '\x1B':
        for sequence, name in keys.iteritems():
            if s.startswith(sequence):
                return s[len(sequence):], TYPE_SPECIAL, name
        
        return s, None, None
    
    if s[0] == '\x7F':
        return s[1:], TYPE_SPECIAL, 'backspace'
    
    if s[0] == '\n':
        return s[1:], TYPE_SPECIAL, 'enter'
    
    if s[0] >= 0x20:
        return s[1:], TYPE_CHAR, s[0]
    
    return s, None, None

def decode(s):
    while len(s) > 0:
        s, ty, v = decode_char(s)
        if ty == None:
            return
        yield (ty, v)

def strip_colors(s):
    return re.sub('\x1B\[\d+m', '', s)
