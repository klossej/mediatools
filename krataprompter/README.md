# KråtaPrompter 1.0

A browser teleprompter with an operator editor, cue navigation and a separate fullscreen presenter. It runs on a production LAN over HTTP with a desktop browser and the supplied Python 3.12 server.

## Start

From the repository:

```bash
cd krataprompter
python3 serve.py
```

Open `http://127.0.0.1:25252/` on the host. To serve on the LAN, bind to the production interface or to all IPv4 interfaces. Open `http://<server-ip>:25252/` on the operator workstation.

```bash
python3 serve.py --bind 0.0.0.0
```

Use `--port` to override 25252. The supplied server serves the app and its script library without a build step. The operator and presenter windows run in the same browser profile on the same workstation. Move the presenter window to the second physical display.

## Server script library

**Save** and **Save As** write ordinary Markdown files to the server with their presentation settings, current reading position and version stamp. The header shows the last saved version of the open script. The operator page automatically opens the last script opened from or saved to the server and starts paused at its saved position. **Open Script** lists all saved scripts. **Import file**, **Download .md** and **Export .txt** support local copies.

The server creates `.krataprompter-data/` at the repository root by default. Use `--data-dir /path/to/scripts` to select a different writable folder. The library and last-script record are shared by operators using that server. Run the service on the trusted production LAN, where anyone who can access the app can open and save scripts.

Before replacing an existing script, the server preserves its exact Markdown in `.revisions/<script name>/` inside the data folder. If archiving fails, the existing script stays in place and the save reports an error. Keep the archive with the live library when backing it up.

## Development

Run `python3 serve.py --dev` for manual testing. It listens on loopback port 25253 by default and uses a separate `.krataprompter-dev-data/` library. Automated tests use their own temporary folders. Keep the live library and its revisions out of development cleanup.

## Optional systemd service

On a host where the checkout is at `/var/lib/srv/mediatools`, save this as `/etc/systemd/system/krataprompter.service`. Replace `YOUR_SERVICE_USER` with a local non-root account that can read the checkout. Change the bind address to the production interface if appropriate.

```ini
[Unit]
Description=KråtaPrompter
After=network.target

[Service]
User=YOUR_SERVICE_USER
WorkingDirectory=/var/lib/srv/mediatools/krataprompter
StateDirectory=krataprompter
StateDirectoryMode=0700
ExecStart=/usr/bin/python3 /var/lib/srv/mediatools/krataprompter/serve.py --bind 0.0.0.0 --port 25252 --data-dir /var/lib/krataprompter
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now krataprompter.service
```

- [Operator guide](docs/OPERATOR_GUIDE.md)
- [Testing and verification](docs/TESTING.md)
- [Implementation handoff](docs/HANDOFF.md)
- [Inter font licence](fonts/Inter-LICENSE.txt)
