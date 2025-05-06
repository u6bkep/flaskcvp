#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
 *  Copyright © 2010, Michael "Svedrin" Ziegler <diese-addy@funzt-halt.net>
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

from distutils.core import setup

setup(name='flaskcvp',
      version="2.5",
      description="Minimalistic CVP Provider using Flask and Mumble-Django's connectors",
      author="Michael Ziegler",
      author_email='diese-addy@funzt-halt.net',
      url='http://www.mumble-django.org',
      py_modules=['flaskcvp', 'mumble.mctl', 'mumble.MumbleCtlDbus', 'mumble.MumbleCtlIce', 'mumble.utils'],
     )
