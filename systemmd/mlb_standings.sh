# For system-level timers, use sudo and omit --user
systemctl --user daemon-reload  # Reload systemd to recognize new timer
systemctl --user enable mlb_standings.timer  # Enable the timer
systemctl --user start mlb_standings.timer  # Start the timer
