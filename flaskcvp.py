#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# kate: space-indent on; indent-width 4; replace-tabs on;

"""
 *  Copyright (C) 2010, Michael "Svedrin" Ziegler <diese-addy@funzt-halt.net>
 *
 *  Mumble-Django is free software; you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation; either version 2 of the License, or
 *  (at your option) any later version.
 *
 *  This package is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
"""
import os
import getpass
import argparse

from flask import Flask, jsonify, request, current_app, render_template, send_from_directory
from functools import wraps

from mumble.mctl import MumbleCtlBase

DEFAULT_CONNSTRING = 'Meta:tcp -h 127.0.0.1 -p 6502'
DEFAULT_SLICEFILE  = '/usr/share/slice/Murmur.ice'
DEFAULT_ICESECRET  = None
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000

# Environment variable names
ENV_CONNSTRING = 'MUMBLE_CONNSTRING'
ENV_ICESECRET = 'MUMBLE_ICESECRET'
ENV_SLICE = 'MUMBLE_SLICE'
ENV_HOST = 'FLASKCVP_HOST'
ENV_PORT = 'FLASKCVP_PORT'

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="""
Usage: %(prog)s [options]

This is a minimalistic implementation of a Channel Viewer Protocol provider
using the Flask Python framework and Mumble-Django's MCTL connection library.
""")

    parser.add_argument("-c", "--connstring",
        help=f"connection string to use. Default is '{DEFAULT_CONNSTRING}'. Can be set with {ENV_CONNSTRING} env var.",
        default=os.environ.get(ENV_CONNSTRING, DEFAULT_CONNSTRING))
    parser.add_argument("-i", "--icesecret",
        help=f"Ice secret to use in the connection. Also see --asksecret. Can be set with {ENV_ICESECRET} env var.",
        default=os.environ.get(ENV_ICESECRET, DEFAULT_ICESECRET))
    parser.add_argument("-a", "--asksecret",
        help="Ask for the Ice secret on the shell instead of taking it from the command line.",
        action="store_true", default=False)
    parser.add_argument("-s", "--slice",
        dest="slice",
        help=f"path to the slice file. Default is '{DEFAULT_SLICEFILE}'. Can be set with {ENV_SLICE} env var.",
        default=os.environ.get(ENV_SLICE, DEFAULT_SLICEFILE))
    parser.add_argument("-d", "--debug",
        help="Enable error debugging",
        action="store_true", default=False)
    parser.add_argument("-H", "--host",
        help=f"The IP to bind to. Default is '{DEFAULT_HOST}'. Can be set with {ENV_HOST} env var.",
        default=os.environ.get(ENV_HOST, DEFAULT_HOST))
    parser.add_argument("-p", "--port",
        type=int,
        help=f"The port number to bind to. Default is {DEFAULT_PORT}. Can be set with {ENV_PORT} env var.",
        default=int(os.environ.get(ENV_PORT, DEFAULT_PORT)))

    args = parser.parse_args()
    options = args
    
    # Only handle the asksecret option as it requires user input
    if options.asksecret:
        options.icesecret = getpass.getpass("Ice secret: ")
else:
    class options:
        connstring = os.environ.get(ENV_CONNSTRING, DEFAULT_CONNSTRING)
        slice = os.environ.get(ENV_SLICE, DEFAULT_SLICEFILE)
        icesecret = os.environ.get(ENV_ICESECRET, DEFAULT_ICESECRET)
        host = os.environ.get(ENV_HOST, DEFAULT_HOST)
        port = int(os.environ.get(ENV_PORT, DEFAULT_PORT))

print("Using connection string: ", options.connstring)
print("Using slice file: ", options.slice)
print("Using Ice secret: ", options.icesecret)
print("Using host: ", options.host)
print("Using port: ", options.port)

ctl = MumbleCtlBase.newInstance( options.connstring, options.slice, options.icesecret )


app = Flask(__name__)

def getUser(user):
    fields = ["channel", "deaf", "mute", "name", "selfDeaf", "selfMute",
        "session", "suppress", "userid", "idlesecs", "recording", "comment",
        "prioritySpeaker"]
    return dict(zip(fields, [getattr(user, field) for field in fields]))

def getChannel(channel):
    fields = ["id", "name", "parent", "links", "description", "temporary", "position"]
    data = dict(zip(fields, [getattr(channel.c, field) for field in fields]))
    data['channels'] = [ getChannel(subchan) for subchan in channel.children ]
    data['users']    = [ getUser(user) for user in channel.users ]
    return data

def support_jsonp(f):
    """Wraps output to JSONP"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        result = f(*args, **kwargs)
        callback = request.args.get('callback', False)
        if callback:
            # Python3: decode response data as text
            data = result.get_data(as_text=True)
            content = f"{callback}({data})"
            return current_app.response_class(content,
                                              mimetype='application/json')
        else:
            return result
    return decorated_function

@app.route('/<int:srv_id>', methods=['GET'])
@support_jsonp
def getTree(srv_id):
    name = ctl.getConf(srv_id, "registername")
    tree = ctl.getTree(srv_id)

    serv = {
        'x_connecturl': os.environ.get('MURMUR_CONNECT_URL'),
        'id':   srv_id,
        'name': name,
        'root': getChannel(tree)
        }
    return jsonify(serv)

@app.route('/')
def getServers():
    return jsonify(servers=ctl.getBootedServers())

if __name__ == '__main__':
    app.run(host=options.host, port=options.port, debug=options.debug)
