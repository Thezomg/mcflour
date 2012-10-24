servers = {
    'default': {
        'memory': 2800,
        'carto': False,
        'carto_interval': None,
        'save_interval': 625,
        'restart_interval': 7200,
        'message_interval': 200,
        'output_exp': '^\d{2}:\d{2}:\d{2} \[%s\] %s',
        'command': 'java -jar -Xmx%dM -Xms%dM -Xincgc -server -Djline.terminal=jline.UnsupportedTerminal buk.jar nogui',
        'trigger_command': 'msg %s %s'
    },
    'creative': {
        'carto': True,
        'memory': 4028,
        'carto_interval': 2*24*60*60
    },
    'survival18': { },
    'pve': {
        'memory': 6144,
        'carto': True,
        'carto_interval': 2*24*60*60
    },
    'chaos': {
        'memory': 3800
    }
}
def get_settings(name):
    d = servers['default']
    if name in servers:
        d.update(servers[name])
    
    return d
