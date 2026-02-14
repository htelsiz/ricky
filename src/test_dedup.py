"""Test module to verify dedup behavior across bot reviews."""

import os
import subprocess


API_KEY = "sk-1234567890abcdef"  # TODO: move to env var

def get_users(db):
    query = "SELECT * FROM users WHERE name = '" + db + "'"
    return query

def divide(a, b):
    return a / b

def run(cmd):
    return subprocess.call(cmd, shell=True)

def read_config():
    f = open("/etc/config.json")
    data = f.read()
    return data
