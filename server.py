import os, uuid, time, math, random, threading
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'leppe-secret-2024'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

lobbies = {}   # id -> lobby
clients = {}   # sid -> {name, lobby_id, team}

TICK = 1/60
GW, GH, MX = 680, 380, 340

PLATFORMS = [
    {'x':0,  'y':370,'w':680,'h':14,'mov':False,'mx':0,'bx':0,  't':0},
    {'x':80, 'y':290,'w':120,'h':12,'mov':False,'mx':0,'bx':80, 't':0},
    {'x':480,'y':290,'w':120,'h':12,'mov':False,'mx':0,'bx':480,'t':0},
    {'x':270,'y':240,'w':140,'h':12,'mov':True, 'mx':60,'bx':270,'t':0},
    {'x':120,'y':180,'w':100,'h':12,'mov':False,'mx':0,'bx':120,'t':0},
    {'x':460,'y':180,'w':100,'h':12,'mov':False,'mx':0,'bx':460,'t':0},
    {'x':280,'y':130,'w':120,'h':12,'mov':False,'mx':0,'bx':280,'t':0},
]
TRAMPS = [
    {'x':50, 'y':356,'w':40,'h':8},
    {'x':590,'y':356,'w':40,'h':8},
]

def new_lobby(name, host_sid, password=''):
    lid = str(uuid.uuid4())[:6].upper()
    return {
        'id': lid, 'name': name, 'host': host_sid,
        'password': password,
        'red': [], 'blue': [],
        'max': 3, 'state': 'waiting', 'game': None
    }

def new_player(sid, name, team):
    x = 120 if team == 'red' else 520
    return {
        'sid': sid, 'name': name[:16], 'team': team,
        'x': float(x), 'y': 200.0,
        'vx': 0.0, 'vy': 0.0,
        'w': 28, 'h': 38,
        'on_ground': False,
        'hp': 5, 'max_hp': 5,
        'alive': True, 'spawn_timer': 0,
        'shield': 0, 'speed': 0, 'multi': 0,
        'facing': 1 if team == 'red' else -1,
        'throw_cd': 0,
        'inputs': {'l':False,'r':False,'u':False,'throw':False}
    }

def new_ball(x, y, vx, vy, owner, btype='normal'):
    return {
        'id': str(uuid.uuid4())[:8],
        'x': float(x), 'y': float(y),
        'vx': float(vx), 'vy': float(vy),
        'r': 7, 'owner': owner, 'type': btype,
        'life': 320, 'bounces': 0
    }

def new_game(lobby):
    import copy
    pls = {}
    for sid in lobby['red']:
        if sid in clients:
            pls[sid] = new_player(sid, clients[sid]['name'], 'red')
    for sid in lobby['blue']:
        if sid in clients:
            pls[sid] = new_player(sid, clients[sid]['name'], 'blue')
    return {
        'players': pls,
        'balls': [],
        'powerups': [],
        'platforms': copy.deepcopy(PLATFORMS),
        'red_score': 0, 'blue_score': 0,
        'timer': 90, 'tick': 0,
        'grav': 1, 'grav_timer': 0,
        'ball_tick': 0, 'pup_tick': 0,
        'running': True
    }

# ── physics ────────────────────────────────────────────

def tick_game(lid):
    if lid not in lobbies: return
    lb = lobbies[lid]
    g = lb.get('game')
    if not g or not g['running']: return

    g['tick'] += 1
    grav = g['grav']

    # timer
    if g['tick'] % 60 == 0:
        g['timer'] -= 1
        if g['timer'] <= 0:
            finish_game(lid); return

    # gravity flip countdown
    if g['grav_timer'] > 0:
        g['grav_timer'] -= 1
        if g['grav_timer'] == 0:
            g['grav'] = 1

    # moving platforms
    for pl in g['platforms']:
        if pl['mov']:
            pl['t'] += 0.02
            pl['x'] = pl['bx'] + math.sin(pl['t']) * pl['mx']

    # spawn balls
    g['ball_tick'] += 1
    if g['ball_tick'] % 80 == 0 and len(g['balls']) < 16:
        t = random.choice(['normal','normal','normal','explosive','split'])
        g['balls'].append(new_ball(
            60 + random.random()*(GW-120), 20,
            (random.random()-.5)*4, -3 - random.random()*5,
            'none', t))

    # spawn powerups
    g['pup_tick'] += 1
    if g['pup_tick'] % 350 == 0 and len(g['powerups']) < 4:
        pt = random.choice(['speed','shield','gravity','multi'])
        g['powerups'].append({
            'id': str(uuid.uuid4())[:6],
            'x': 60 + random.random()*(GW-120),
            'y': 40 + random.random()*280,
            'type': pt, 'r': 12, 'life': 600
        })
    for pu in g['powerups']: pu['life'] -= 1
    g['powerups'] = [p for p in g['powerups'] if p['life'] > 0]

    # players
    for sid, p in list(g['players'].items()):
        if not p['alive']:
            if p['spawn_timer'] > 0:
                p['spawn_timer'] -= 1
                if p['spawn_timer'] == 0:
                    p['alive'] = True
                    p['hp'] = p['max_hp']
                    p['x'] = 120.0 if p['team']=='red' else 520.0
                    p['y'] = 100.0
                    p['vx'] = p['vy'] = 0.0
            continue

        inp = p['inputs']
        spd = 2.8 * (1.6 if p['speed'] > 0 else 1.0)

        if inp['l']:   p['vx'] = max(p['vx']-.4, -spd); p['facing'] = -1
        elif inp['r']: p['vx'] = min(p['vx']+.4,  spd); p['facing'] =  1
        else:          p['vx'] *= 0.82

        p['vy'] += 0.35 * grav
        p['x']  += p['vx']
        p['y']  += p['vy']
        p['on_ground'] = False

        for pl in g['platforms']:
            inX = p['x']+p['w'] > pl['x'] and p['x'] < pl['x']+pl['w']
            if not inX: continue
            if grav==1 and p['vy']>=0 and p['y']+p['h']>pl['y'] and p['y']+p['h']<pl['y']+pl['h']+16:
                p['y'] = pl['y']-p['h']; p['vy'] = 0; p['on_ground'] = True
            elif grav==-1 and p['vy']<=0 and p['y']<pl['y']+pl['h'] and p['y']>pl['y']-16:
                p['y'] = pl['y']+pl['h']; p['vy'] = 0; p['on_ground'] = True

        for tr in TRAMPS:
            inX = p['x']+p['w']>tr['x'] and p['x']<tr['x']+tr['w']
            if grav==1 and p['y']+p['h']>tr['y'] and p['y']+p['h']<tr['y']+20 and inX:
                p['vy'] = -16; p['on_ground'] = False

        if p['team']=='red': p['x'] = max(0.0, min(float(MX-p['w']), p['x']))
        else:                p['x'] = max(float(MX), min(float(GW-p['w']), p['x']))
        if grav==1 and p['y']>GH+50:  p['y']=100.0; p['vy']=0.0
        if grav==-1 and p['y']<-50:   p['y']=100.0; p['vy']=0.0

        if inp['u'] and p['on_ground']:
            p['vy'] = -9.5*grav; p['on_ground'] = False

        if p['throw_cd'] > 0: p['throw_cd'] -= 1
        if p['speed']    > 0: p['speed']    -= 1

        if inp['throw'] and p['throw_cd'] == 0:
            inp['throw'] = False
            p['throw_cd'] = 22
            count = 2 if p['multi'] > 0 else 1
            if p['multi'] > 0: p['multi'] -= 1
            types = ['normal','normal','normal','explosive','split']
            for i in range(count):
                t = random.choice(types)
                bvx = p['facing']*12 + (random.random()-.5)*3*i
                bvy = -3.0 + (random.random()-.5)*2*i
                g['balls'].append(new_ball(
                    p['x']+(p['w'] if p['facing']>0 else 0),
                    p['y']+p['h']*.4,
                    bvx, bvy, p['team'], t))

        # powerup pickup
        for pu in list(g['powerups']):
            dx = (p['x']+p['w']/2)-pu['x']
            dy = (p['y']+p['h']/2)-pu['y']
            if math.sqrt(dx*dx+dy*dy) < pu['r']+p['w']/2:
                apply_pup(g, p, pu['type'], lid)
                g['powerups'].remove(pu)

    # balls
    to_kill = set()
    new_balls = []
    for bi, b in enumerate(g['balls']):
        if bi in to_kill: continue
        b['vx'] *= 0.995
        b['vy'] += 0.32 * grav
        b['x']  += b['vx']
        b['y']  += b['vy']
        b['life'] -= 1
        if b['life'] <= 0: to_kill.add(bi); continue

        for pl in g['platforms']:
            inX = b['x']+b['r']>pl['x'] and b['x']-b['r']<pl['x']+pl['w']
            if grav==1 and b['vy']>0 and b['y']+b['r']>pl['y'] and b['y']-b['r']<pl['y']+12 and inX:
                b['y']=pl['y']-b['r']; b['vy']*=-.62; b['vx']*=.9; b['bounces']+=1
            elif grav==-1 and b['vy']<0 and b['y']-b['r']<pl['y']+pl['h'] and b['y']+b['r']>pl['y'] and inX:
                b['y']=pl['y']+pl['h']+b['r']; b['vy']*=-.62; b['vx']*=.9; b['bounces']+=1

        for tr in TRAMPS:
            inX = b['x']+b['r']>tr['x'] and b['x']-b['r']<tr['x']+tr['w']
            if b['y']+b['r']>tr['y'] and b['y']-b['r']<tr['y']+10 and inX:
                b['vy'] *= -1.5; b['bounces'] += 1

        if b['x']-b['r'] < 0:  b['x']=b['r'];    b['vx']=abs(b['vx']);  b['bounces']+=1
        if b['x']+b['r'] > GW: b['x']=GW-b['r']; b['vx']=-abs(b['vx']); b['bounces']+=1
        if grav==1  and b['y']+b['r'] > GH: b['y']=GH-b['r']; b['vy']*=-.5; b['bounces']+=1
        if grav==-1 and b['y']-b['r'] < 0:  b['y']=b['r'];    b['vy']*=-.5; b['bounces']+=1

        if b['bounces'] > 8 and b['type']=='explosive':
            explode(g, b); to_kill.add(bi); continue
        if b['bounces'] > 14: to_kill.add(bi); continue

        hit_sid = None
        for sid, p in g['players'].items():
            if not p['alive'] or bi in to_kill: continue
            cx = p['x']+p['w']/2; cy = p['y']+p['h']/2
            if abs(b['x']-cx)<p['w']/2+b['r'] and abs(b['y']-cy)<p['h']/2+b['r']:
                if b['type']=='split':
                    split_ball(g, b); to_kill.add(bi)
                elif b['type']=='explosive':
                    explode(g, b); to_kill.add(bi)
                else:
                    hit_player(g, sid, b); to_kill.add(bi)
                hit_sid = sid; break

    g['balls'] = [b for i,b in enumerate(g['balls']) if i not in to_kill] + new_balls

    socketio.emit('state', serialize(g), room=lid)

def hit_player(g, sid, b):
    p = g['players'].get(sid)
    if not p or not p['alive']: return
    if p['shield'] > 0: p['shield'] -= 1; return
    p['hp'] -= 1
    if b: p['vx']+=b['vx']*.3; p['vy']-=3
    if p['hp'] <= 0:
        p['alive']=False; p['spawn_timer']=150
        if p['team']=='red': g['blue_score']+=1
        else:                g['red_score']+=1

def explode(g, b):
    for sid, p in list(g['players'].items()):
        if not p['alive']: continue
        dx=(p['x']+p['w']/2)-b['x']; dy=(p['y']+p['h']/2)-b['y']
        if math.sqrt(dx*dx+dy*dy) < 70: hit_player(g, sid, b)

def split_ball(g, b):
    spd = math.sqrt(b['vx']**2+b['vy']**2)*.8
    ba  = math.atan2(b['vy'], b['vx'])
    for i in range(3):
        a = ba+(math.pi*2/3)*i
        nb = new_ball(b['x'],b['y'],math.cos(a)*spd,math.sin(a)*spd,b['owner'],'normal')
        nb['r']=5; nb['life']=120
        g['balls'].append(nb)

def apply_pup(g, p, ptype, lid):
    if ptype=='speed':   p['speed']=180
    elif ptype=='shield':p['shield']+=2
    elif ptype=='multi': p['multi']=3
    elif ptype=='gravity':
        g['grav'] *= -1; g['grav_timer']=200
        socketio.emit('grav_flip', {'dir':g['grav']}, room=lid)

def finish_game(lid):
    lb = lobbies.get(lid)
    if not lb or not lb['game']: return
    g = lb['game']
    g['running'] = False
    lb['state'] = 'waiting'
    w = 'red' if g['red_score']>g['blue_score'] else ('blue' if g['blue_score']>g['red_score'] else 'draw')
    socketio.emit('game_over', {'winner':w,'red':g['red_score'],'blue':g['blue_score']}, room=lid)

def serialize(g):
    return {
        'players':  {sid: {k:v for k,v in p.items() if k!='inputs'} for sid,p in g['players'].items()},
        'balls':    g['balls'],
        'powerups': g['powerups'],
        'platforms': g['platforms'],
        'rs': g['red_score'], 'bs': g['blue_score'],
        'timer': g['timer'], 'grav': g['grav']
    }

def lobby_info(lb):
    def nm(sid): return clients.get(sid,{}).get('name','?')
    return {
        'id':  lb['id'], 'name': lb['name'],
        'host': lb['host'], 'host_name': nm(lb['host']),
        'red':  [{'sid':s,'name':nm(s)} for s in lb['red']],
        'blue': [{'sid':s,'name':nm(s)} for s in lb['blue']],
        'max':  lb['max'], 'state': lb['state'],
        'locked': bool(lb['password'])
    }

def broadcast_lobbies():
    socketio.emit('lobby_list', [lobby_info(lb) for lb in lobbies.values()])

def game_loop(lid):
    while lid in lobbies and lobbies[lid].get('game') and lobbies[lid]['game']['running']:
        t0 = time.time()
        tick_game(lid)
        elapsed = time.time()-t0
        time.sleep(max(0, TICK-elapsed))

# ── socket events ──────────────────────────────────────

@socketio.on('connect')
def on_connect():
    clients[request.sid] = {'name':'Leppie','lobby_id':None,'team':None}
    emit('hello', {'sid': request.sid})

@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    c = clients.pop(sid, {})
    lid = c.get('lobby_id')
    if lid and lid in lobbies:
        lb = lobbies[lid]
        lb['red']  = [s for s in lb['red']  if s!=sid]
        lb['blue'] = [s for s in lb['blue'] if s!=sid]
        if lb['game'] and sid in lb['game']['players']:
            lb['game']['players'].pop(sid)
        if lb['host']==sid:
            all_p = lb['red']+lb['blue']
            if all_p: lb['host']=all_p[0]
            else:
                lobbies.pop(lid, None)
                broadcast_lobbies(); return
        leave_room(lid)
        socketio.emit('lobby_update', lobby_info(lb), room=lid)
    broadcast_lobbies()

@socketio.on('set_name')
def on_set_name(data):
    clients[request.sid]['name'] = data.get('name','Leppie')[:16]

@socketio.on('get_lobbies')
def on_get_lobbies():
    emit('lobby_list', [lobby_info(lb) for lb in lobbies.values()])

@socketio.on('create_lobby')
def on_create(data):
    sid = request.sid
    lb = new_lobby(data.get('name','Arena'), sid, data.get('password',''))
    lobbies[lb['id']] = lb
    lb['red'].append(sid)
    clients[sid]['lobby_id'] = lb['id']
    clients[sid]['team'] = 'red'
    join_room(lb['id'])
    emit('joined', {'lobby': lobby_info(lb), 'team':'red', 'sid': sid})
    broadcast_lobbies()

@socketio.on('join_lobby')
def on_join(data):
    sid = request.sid
    lid = data.get('id')
    team = data.get('team','red')
    pw   = data.get('password','')
    if lid not in lobbies: emit('err',{'msg':'Lobby not found'}); return
    lb = lobbies[lid]
    if lb['password'] and lb['password']!=pw: emit('err',{'msg':'Wrong password'}); return
    if lb['state']=='ingame': emit('err',{'msg':'Game already in progress'}); return
    if team=='red'  and len(lb['red']) >=lb['max']: emit('err',{'msg':'Red team is full'}); return
    if team=='blue' and len(lb['blue'])>=lb['max']: emit('err',{'msg':'Blue team is full'}); return

    old = clients[sid].get('lobby_id')
    if old and old in lobbies:
        ol=lobbies[old]; ol['red']=[s for s in ol['red'] if s!=sid]; ol['blue']=[s for s in ol['blue'] if s!=sid]
        leave_room(old); socketio.emit('lobby_update', lobby_info(ol), room=old)

    if team=='red': lb['red'].append(sid)
    else:           lb['blue'].append(sid)
    clients[sid]['lobby_id']=lid; clients[sid]['team']=team
    join_room(lid)
    emit('joined', {'lobby': lobby_info(lb), 'team':team, 'sid':sid})
    socketio.emit('lobby_update', lobby_info(lb), room=lid)
    broadcast_lobbies()

@socketio.on('switch_team')
def on_switch(data):
    sid=request.sid; lid=clients[sid].get('lobby_id'); team=data.get('team')
    if not lid or lid not in lobbies: return
    lb=lobbies[lid]
    if team=='red'  and len(lb['red']) >=lb['max']: emit('err',{'msg':'Red team full'}); return
    if team=='blue' and len(lb['blue'])>=lb['max']: emit('err',{'msg':'Blue team full'}); return
    lb['red']=[s for s in lb['red'] if s!=sid]; lb['blue']=[s for s in lb['blue'] if s!=sid]
    if team=='red': lb['red'].append(sid)
    else:           lb['blue'].append(sid)
    clients[sid]['team']=team
    socketio.emit('lobby_update', lobby_info(lb), room=lid)
    broadcast_lobbies()

@socketio.on('leave_lobby')
def on_leave():
    sid=request.sid; lid=clients[sid].get('lobby_id')
    if not lid or lid not in lobbies: emit('left'); return
    lb=lobbies[lid]
    lb['red']=[s for s in lb['red'] if s!=sid]; lb['blue']=[s for s in lb['blue'] if s!=sid]
    leave_room(lid); clients[sid]['lobby_id']=None; clients[sid]['team']=None
    if lb['game'] and sid in lb['game']['players']:
        lb['game']['players'].pop(sid)
    if lb['host']==sid:
        all_p=lb['red']+lb['blue']
        if all_p: lb['host']=all_p[0]
        else: lobbies.pop(lid,None); broadcast_lobbies(); emit('left'); return
    socketio.emit('lobby_update', lobby_info(lb), room=lid)
    broadcast_lobbies(); emit('left')

@socketio.on('delete_lobby')
def on_delete():
    sid=request.sid; lid=clients[sid].get('lobby_id')
    if not lid or lid not in lobbies: return
    lb=lobbies[lid]
    if lb['host']!=sid: emit('err',{'msg':'Only host can delete'}); return
    all_sids=lb['red']+lb['blue']
    for s in all_sids:
        if s in clients: clients[s]['lobby_id']=None; clients[s]['team']=None
    if lb['game']: lb['game']['running']=False
    socketio.emit('lobby_deleted', {}, room=lid)
    lobbies.pop(lid,None); broadcast_lobbies()

@socketio.on('start_game')
def on_start():
    sid=request.sid; lid=clients[sid].get('lobby_id')
    if not lid or lid not in lobbies: return
    lb=lobbies[lid]
    if lb['host']!=sid: emit('err',{'msg':'Only host can start'}); return
    if not lb['red'] or not lb['blue']: emit('err',{'msg':'Need at least 1 player per team'}); return
    lb['state']='ingame'; lb['game']=new_game(lb)
    socketio.emit('game_start', {}, room=lid)
    threading.Thread(target=game_loop, args=(lid,), daemon=True).start()

@socketio.on('input')
def on_input(data):
    sid=request.sid; lid=clients[sid].get('lobby_id')
    if not lid or lid not in lobbies: return
    lb=lobbies[lid]; g=lb.get('game')
    if not g: return
    p=g['players'].get(sid)
    if not p: return
    inp=data.get('i',{})
    p['inputs']['l']=bool(inp.get('l'))
    p['inputs']['r']=bool(inp.get('r'))
    p['inputs']['u']=bool(inp.get('u'))
    if inp.get('t'): p['inputs']['throw']=True

@app.route('/')
def index(): return render_template('index.html')

if __name__ == "__main__":
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), allow_unsafe_werkzeug=True)
