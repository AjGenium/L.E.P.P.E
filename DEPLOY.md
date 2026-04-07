# L.E.P.P.E — Deploy Guide

## Run locally first (test it works)
```
pip install flask flask-socketio eventlet
python server.py
# open http://localhost:5000
```

---

## Deploy to Railway (5 steps)

1. Push this folder to a GitHub repo (can be private)
   ```
   git init
   git add .
   git commit -m "leppe"
   gh repo create leppe --private --push  # or use github.com
   ```

2. Go to https://railway.app → "New Project" → "Deploy from GitHub repo"

3. Select your repo. Railway auto-detects the Procfile.

4. In your Railway project → Settings → "Generate Domain"
   You get a URL like: `https://leppe-production.up.railway.app`

5. Share that URL. Anyone can open it and play.

---

## Controls (everyone uses these on their own computer)
| Action | Key |
|--------|-----|
| Move left/right | A / D |
| Jump | W |
| Throw | F |

---

## Lobby rules
- Anyone can create a lobby (optional password)
- Host can delete the lobby or start the game
- Players can leave mid-game via ☰ MENU button — takes them back to menu
- Switch teams by clicking JOIN on the other team's side
- Game runs at 60 ticks/sec server-side; clients render at their own framerate

---

## Friendly fire
Balls damage ALL players — including teammates. Chaos intended.
