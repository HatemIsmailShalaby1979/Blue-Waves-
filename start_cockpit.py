#!/usr/bin/env python3
"""Start Blue Waves Cockpit server."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
os.chdir(os.path.dirname(__file__))

from blue_waves.application import BlueWavesApplication
from blue_waves.cockpit_server import start_cockpit

print("Blue Waves Cockpit v0.2.0")
print("Starting server on http://0.0.0.0:8420")
print("Press Ctrl+C to stop")

app = BlueWavesApplication()
start_cockpit(app, host="0.0.0.0", port=8420)
