import ansiterm

class Prompt:
    text = ''
    prefix = '% '
    cursor = 0
    
    history = ['']
    history_pos = 0
    
    def __init__(self, command_callback):
        self.command_callback = command_callback
    
    def save_prompt(self):
        self.history[self.history_pos] = self.text
    
    def load_prompt(self):
        self.text = self.history[self.history_pos]
        self.cursor = len(self.text)
    
    def __repr__(self):
        #Write prompt
        o = self.prefix + self.text
        
        #Position cursor
        o += '\r' + '\x1B[C' * (self.cursor+len(self.prefix))
        
        return o

    def write(self, data):
        for ty, key in ansiterm.decode(data):
            if ty == ansiterm.TYPE_CHAR:
                self.text = self.text[:self.cursor] + key + self.text[self.cursor:]
                self.cursor +=1
            else:
                self.write_special_key(key)
    
    def write_special_key(self, key):
        ### Delete/backspace
        if key == 'delete':
            self.text = self.text[:self.cursor] + self.text[self.cursor+1:]
        
        elif key == 'backspace':
            if self.cursor > 0:
                self.cursor -= 1
                self.text = self.text[:self.cursor] + self.text[self.cursor+1:]
        
        ### Cursor left/right
        elif key == 'arrow_left':
            self.cursor = max(self.cursor-1, 0)
        elif key == 'arrow_right':
            self.cursor = min(self.cursor+1, len(self.text))
        
        ### Home/end
        elif key == 'home':
            self.cursor = 0
        elif key == 'end':
            self.cursor = len(self.text)
        
        ### Scrollback (cursor up/down)
        elif key == 'arrow_up':
            if self.history_pos > 0:
                self.save_prompt()
                self.history_pos -= 1
                self.load_prompt()
        elif key == 'arrow_down':
            if self.history_pos < len(self.history)-1:
                self.save_prompt()
                self.history_pos += 1
                self.load_prompt()
        
        ### Enter
        elif key == 'enter':
            self.command_callback(self.text)
            self.history_pos = len(self.history) - 1
            if self.history[self.history_pos-1] == self.text:
                self.text = ''
                self.cursor = 0
                self.save_prompt()
            else:
                self.save_prompt()
                self.history.append('')
                self.history_pos += 1
                self.load_prompt()
        
