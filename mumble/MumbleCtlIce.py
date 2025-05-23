# -*- coding: utf-8 -*-
# kate: space-indent on; indent-width 4; replace-tabs on;

"""
 *  Copyright © 2009, withgod                   <withgod@sourceforge.net>
 *         2009-2010, Michael "Svedrin" Ziegler <diese-addy@funzt-halt.net>
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

from time        import time
from functools   import wraps
from io          import BytesIO
from os.path     import exists, join
from os          import unlink, name as os_name
from PIL         import Image
from struct      import pack, unpack
from zlib        import compress, decompress, error

from .mctl import MumbleCtlBase

from .utils import ObjectInfo

import Ice, IcePy, tempfile


def loadSlice( slicefile ):
    """ Load the slice file with the correct include dir set, if possible. """
    if hasattr( Ice, "getSliceDir" ):
        icepath = Ice.getSliceDir()
    else:
        icepath = None

    # Ice returns '' in getSliceDir() sometimes. (I kid you not.)
    if not icepath:
        try:
            from django.conf import settings
        except ImportError:
            # CTL is being used independently from MD
            icepath = None
        else:
            icepath = settings.SLICEDIR
            if not exists( join( icepath, "Ice", "SliceChecksumDict.ice" ) ):
                icepath = None

    if not icepath:
        # last resort when getSliceDir fails AND settings are wrong/unavailable, won't work for >=1.2.3
        Ice.loadSlice( slicefile )
    else:
        Ice.loadSlice( '', ['-I' + icepath, slicefile ] )


def protectDjangoErrPage( func ):
    """ Catch and reraise Ice exceptions to prevent the Django page from failing.

        Since I need to "import Murmur", Django would try to read a murmur.py file
        which doesn't exist, and thereby produce an IndexError exception. This method
        erases the exception's traceback, preventing Django from trying to read any
        non-existant files and borking.
    """

    @wraps(func)
    def protection_wrapper(self, *args, **kwargs):
        """ Call the original function and catch Ice exceptions. """
        try:
            return func( self, *args, **kwargs )
        except Ice.Exception as err:
            raise err
    protection_wrapper.innerfunc = func

    return protection_wrapper


@protectDjangoErrPage
def MumbleCtlIce( connstring, slicefile=None, icesecret=None ):
    """ Choose the correct Ice handler to use (1.1.8 or 1.2.x), and make sure the
        Murmur version matches the slice Version.

        Optional parameters are the path to the slice file and the Ice secret
        necessary to authenticate to Murmur.

        The path can be omitted only if running Murmur 1.2.3 or later, which
        exports a getSlice method to retrieve the Slice from.
    """

    prop = Ice.createProperties([])
    prop.setProperty("Ice.ImplicitContext", "Shared")
    prop.setProperty("Ice.MessageSizeMax",  "65535")

    idd = Ice.InitializationData()
    idd.properties = prop

    ice = Ice.initialize(idd)

    if icesecret:
        ice.getImplicitContext().put( "secret", icesecret )

    print("Using connection string: %s" % connstring)

    prx = ice.stringToProxy( connstring )

    try:
        prx.ice_ping()
    except Ice.Exception:
        raise EnvironmentError( "Murmur does not appear to be listening on this address (Ice ping failed)." )

    try:
        import MumbleServer
    except ImportError:
        # Try loading the Slice from Murmur directly via its getSlice method.
        # See scripts/testdynamic.py in Mumble's Git repository.
        try:
            slice = IcePy.Operation( 'getSlice',
                Ice.OperationMode.Idempotent, Ice.OperationMode.Idempotent,
                True, (), (), (), IcePy._t_string, ()
                ).invoke(prx, ((), None))
        except (TypeError, Ice.OperationNotExistException):
            if not slicefile:
                raise EnvironmentError(
                    "You didn't configure a slice file. Please set the SLICE variable in settings.py." )
            if not exists( slicefile ):
                raise EnvironmentError(
                    "The slice file does not exist: '%s' - please check the settings." % slicefile )
            if " " in slicefile:
                raise EnvironmentError(
                    "You have a space char in your Slice path. This will confuse Ice, please check." )
            if not slicefile.endswith( ".ice" ):
                raise EnvironmentError( "The slice file name MUST end with '.ice'." )

            try:
                loadSlice( slicefile )
            except RuntimeError:
                raise RuntimeError( "Slice preprocessing failed. Please check your server's error log." )
        else:
            if os_name == "nt":
                # It weren't Windows if it didn't need to be treated differently. *sigh*
                temppath = join( tempfile.gettempdir(), "MumbleServer.ice" )
                slicetemp = open( temppath, "w+b" )
                try:
                    slicetemp.write( slice )
                finally:
                    slicetemp.close()
                try:
                    loadSlice( temppath )
                except RuntimeError:
                    raise RuntimeError( "Slice preprocessing failed. Please check your server's error log." )
                finally:
                    unlink(temppath)
            else:
                slicetemp = tempfile.NamedTemporaryFile( suffix='.ice' )
                try:
                    slicetemp.write( slice )
                    slicetemp.flush()
                    loadSlice( slicetemp.name )
                except RuntimeError:
                    raise RuntimeError( "Slice preprocessing failed. Please check your server's error log." )
                finally:
                    slicetemp.close()

        import MumbleServer

    meta = MumbleServer.MetaPrx.checkedCast(prx)

    murmurversion = meta.getVersion()[:3]

    if murmurversion >= (1, 5, 0):
        return MumbleCtlIce_150(connstring, meta)
    elif murmurversion == (1, 1, 8):
        return MumbleCtlIce_118( connstring, meta )
    elif ((murmurversion[0] == 1) and (murmurversion[1] >= 3)):
        return MumbleCtlIce_123( connstring, meta )
    raise NotImplementedError( "No ctl object available for Murmur version %d.%d.%d" % tuple(murmurversion) )


class MumbleCtlIce_118(MumbleCtlBase):
    method = "ICE"

    def __init__( self, connstring, meta ):
        self.proxy  = connstring
        self.meta   = meta

    @protectDjangoErrPage
    def _getIceServerObject(self, srvid):
        return self.meta.getServer(srvid)

    @protectDjangoErrPage
    def getBootedServers(self):
        ret = []
        for x in self.meta.getBootedServers():
            ret.append(x.id())
        return ret

    @protectDjangoErrPage
    def getVersion( self ):
        return self.meta.getVersion()

    @protectDjangoErrPage
    def getAllServers(self):
        ret = []
        for x in self.meta.getAllServers():
            ret.append(x.id())
        return ret

    @protectDjangoErrPage
    def getRegisteredPlayers(self, srvid, filter = ''):
        users = self._getIceServerObject(srvid).getRegisteredPlayers( filter.encode( "UTF-8" ) )
        ret = {}

        for user in users:
            ret[user.playerid] = ObjectInfo(
                userid =     int( user.playerid ),
                name   = user.name.decode( "utf8" ),
                email  = user.email.decode( "utf8" ),
                pw     = user.pw.decode( "utf8" )
                )

        return ret

    @protectDjangoErrPage
    def getChannels(self, srvid):
        return self._getIceServerObject(srvid).getChannels()

    @protectDjangoErrPage
    def getTree(self, srvid):
        return self._getIceServerObject(srvid).getTree()

    @protectDjangoErrPage
    def getPlayers(self, srvid):
        users = self._getIceServerObject(srvid).getPlayers()

        ret = {}

        for useridx in users:
            user = users[useridx]
            ret[ user.session ] = ObjectInfo(
                session      = user.session,
                userid       = user.playerid,
                mute         = user.mute,
                deaf         = user.deaf,
                suppress     = user.suppressed,
                selfMute     = user.selfMute,
                selfDeaf     = user.selfDeaf,
                channel      = user.channel,
                name         = user.name,
                onlinesecs   = user.onlinesecs,
                bytespersec  = user.bytespersec
                )

        return ret

    @protectDjangoErrPage
    def getDefaultConf(self):
        return self.setUnicodeFlag(self.meta.getDefaultConf())

    @protectDjangoErrPage
    def getAllConf(self, srvid):
        conf = self.setUnicodeFlag(self._getIceServerObject(srvid).getAllConf())

        info = {}
        for key in conf:
            if key == "playername":
                info['username'] = conf[key]
            else:
                info[str(key)] = conf[key]
        return info

    @protectDjangoErrPage
    def newServer(self):
        return self.meta.newServer().id()

    @protectDjangoErrPage
    def isBooted( self, srvid ):
        return bool( self._getIceServerObject(srvid).isRunning() )

    @protectDjangoErrPage
    def start( self, srvid ):
        self._getIceServerObject(srvid).start()

    @protectDjangoErrPage
    def stop( self, srvid ):
        self._getIceServerObject(srvid).stop()

    @protectDjangoErrPage
    def deleteServer( self, srvid ):
        if self._getIceServerObject(srvid).isRunning():
            self._getIceServerObject(srvid).stop()
        self._getIceServerObject(srvid).delete()

    @protectDjangoErrPage
    def setSuperUserPassword(self, srvid, value):
        self._getIceServerObject(srvid).setSuperuserPassword( value.encode( "UTF-8" ) )

    @protectDjangoErrPage
    def getConf(self, srvid, key):
        if key == "username":
            key = "playername"

        return self._getIceServerObject(srvid).getConf( key )

    @protectDjangoErrPage
    def setConf(self, srvid, key, value):
        if key == "username":
            key = "playername"
        if value is None:
            value = ''
        self._getIceServerObject(srvid).setConf( key, value.encode( "UTF-8" ) )

    @protectDjangoErrPage
    def registerPlayer(self, srvid, name, email, password):
        mumbleid = self._getIceServerObject(srvid).registerPlayer( name.encode( "UTF-8" ) )
        self.setRegistration( srvid, mumbleid, name, email, password )
        return mumbleid

    @protectDjangoErrPage
    def unregisterPlayer(self, srvid, mumbleid):
        self._getIceServerObject(srvid).unregisterPlayer(mumbleid)

    @protectDjangoErrPage
    def getRegistration(self, srvid, mumbleid):
        user = self._getIceServerObject(srvid).getRegistration(mumbleid)
        return ObjectInfo(
            userid = mumbleid,
            name   = user.name,
            email  = user.email,
            pw     = '',
            )

    @protectDjangoErrPage
    def setRegistration(self, srvid, mumbleid, name, email, password):
        import Murmur
        user = Murmur.RegisteredPlayer()
        user.playerid = mumbleid
        user.name     = name.encode( "UTF-8" )
        user.email    = email.encode( "UTF-8" )
        user.pw       = password.encode( "UTF-8" )
        # update*r*egistration r is lowercase...
        return self._getIceServerObject(srvid).updateregistration(user)

    @protectDjangoErrPage
    def getACL(self, srvid, channelid):
        # need to convert acls to say "userid" instead of "playerid". meh.
        raw_acls, raw_groups, raw_inherit = self._getIceServerObject(srvid).getACL(channelid)

        acls =  [ ObjectInfo(
                applyHere = rule.applyHere,
                applySubs = rule.applySubs,
                inherited = rule.inherited,
                userid    = rule.playerid,
                group     = rule.group,
                allow     = rule.allow,
                deny      = rule.deny,
                )
            for rule in raw_acls
            ]

        return acls, raw_groups, raw_inherit

    @protectDjangoErrPage
    def setACL(self, srvid, channelid, acls, groups, inherit):
        import Murmur

        ice_acls = []

        for rule in acls:
            ice_rule = Murmur.ACL()
            ice_rule.applyHere = rule.applyHere
            ice_rule.applySubs = rule.applySubs
            ice_rule.inherited = rule.inherited
            ice_rule.playerid  = rule.userid
            ice_rule.group     = rule.group
            ice_rule.allow     = rule.allow
            ice_rule.deny      = rule.deny
            ice_acls.append(ice_rule)

        return self._getIceServerObject(srvid).setACL( channelid, ice_acls, groups, inherit )

    @protectDjangoErrPage
    def getTexture(self, srvid, mumbleid):
        texture = self._getIceServerObject(srvid).getTexture(mumbleid)
        if len(texture) == 0:
            raise ValueError( "No Texture has been set." )
        # this returns a list of bytes.
        try:
            decompressed = decompress(texture)
        except error as err:
            raise ValueError(err)
        # iterate over 4 byte chunks of the string
        imgdata = ""
        for idx in range( 0, len(decompressed), 4 ):
            # read 4 bytes = BGRA and convert to RGBA
            # manual wrote getTexture returns "Textures are stored as zlib compress()ed 600x60 32-bit RGBA data."
            # http://mumble.sourceforge.net/slice/Murmur/Server.html#getTexture
            # but return values BGRA X(
            bgra = unpack( "4B", decompressed[idx:idx+4] )
            imgdata += pack( "4B",  bgra[2], bgra[1], bgra[0], bgra[3] )

        # return a 600x60 RGBA image object created from the data
        return Image.frombytes("RGBA", (600, 60), imgdata)

    @protectDjangoErrPage
    def setTexture(self, srvid, mumbleid, infile):
        # open image, convert to RGBA, and resize to 600x60
        img = infile.convert( "RGBA" ).transform( ( 600, 60 ), Image.EXTENT, ( 0, 0, 600, 60 ) )
        # iterate over the list and pack everything into a string
        # Python 3: use bytes for binary data
        bgrastring = b""
        for ent in img.getdata():
            bgrastring += pack("4B", ent[2], ent[1], ent[0], ent[3])
        # compress using zlib
        compressed = compress( bgrastring )
        # pack the original length in 4 byte big endian, and concat the compressed
        # data to it to emulate qCompress().
        texture = pack( ">L", len(bgrastring) ) + compressed
        # finally call murmur and set the texture
        self._getIceServerObject(srvid).setTexture(mumbleid, texture)

    @protectDjangoErrPage
    def verifyPassword(self, srvid, username, password):
        return self._getIceServerObject(srvid).verifyPassword(username, password)

    @staticmethod
    def setUnicodeFlag(data):
        ret = ''
        if isinstance(data, tuple) or isinstance(data, list) or isinstance(data, dict):
            ret = {}
            for key in data.keys():
                ret[MumbleCtlIce_118.setUnicodeFlag(key)] = MumbleCtlIce_118.setUnicodeFlag(data[key])
        else:
            if isinstance(data, bytes):
                ret = data.decode('utf-8')
            else:
                ret = str(data)

        return ret

    def getUptime(self, srvid):
        return None

    @protectDjangoErrPage
    def getBans( self, srvid ):
        return self._getIceServerObject(srvid).getBans()

    @protectDjangoErrPage
    def getLog( self, srvid, first=0, last=100 ):
        return self._getIceServerObject(srvid).getLog( first, last )

    @protectDjangoErrPage
    def addChannel( self, srvid, name, parentid ):
        return self._getIceServerObject(srvid).addChannel( name.encode( "UTF-8" ), parentid )

    @protectDjangoErrPage
    def removeChannel( self, srvid, channelid ):
        return self._getIceServerObject(srvid).removeChannel( channelid )

    @protectDjangoErrPage
    def renameChannel( self, srvid, channelid, name, description ):
        srv = self._getIceServerObject(srvid)
        state = srv.getChannelState(channelid)
        state.name = name.encode("UTF-8")
        srv.setChannelState(state)

    @protectDjangoErrPage
    def moveChannel(self, srvid, channelid, parentid):
        srv = self._getIceServerObject(srvid)
        state = srv.getChannelState(channelid)
        state.parent = parentid
        srv.setChannelState(state)

    @protectDjangoErrPage
    def moveUser(self, srvid, sessionid, channelid):
        srv = self._getIceServerObject(srvid)
        state = srv.getState(sessionid)
        state.channel = channelid
        srv.setState(state)

    @protectDjangoErrPage
    def muteUser(self, srvid, sessionid, mute=True):
        srv = self._getIceServerObject(srvid)
        state = srv.getState(sessionid)
        state.mute = mute
        srv.setState(state)

    @protectDjangoErrPage
    def deafenUser(self, srvid, sessionid, deaf=True):
        srv = self._getIceServerObject(srvid)
        state = srv.getState(sessionid)
        state.deaf = deaf
        srv.setState(state)

    @protectDjangoErrPage
    def kickUser(self, srvid, userid, reason=""):
        return self._getIceServerObject(srvid).kickPlayer( userid, reason.encode("UTF-8") )

    @protectDjangoErrPage
    def sendMessage(self, srvid, sessionid, message):
        return self._getIceServerObject(srvid).sendMessage( sessionid, message.encode( "UTF-8" ) )

    @protectDjangoErrPage
    def sendMessageChannel(self, srvid, channelid, tree, message):
        return self._getIceServerObject(srvid).sendMessageChannel( channelid, tree, message.encode( "UTF-8" ) )


class MumbleCtlIce_120(MumbleCtlIce_118):
    @protectDjangoErrPage
    def getRegisteredPlayers(self, srvid, filter = ''):
        users = self._getIceServerObject( srvid ).getRegisteredUsers( filter.encode( "UTF-8" ) )
        ret = {}

        for id in users:
            ret[id] = ObjectInfo(
                userid = id,
                name   = users[id].decode( "utf8" ),
                email  = '',
                pw     = ''
                )

        return ret

    @protectDjangoErrPage
    def getPlayers(self, srvid):
        userdata = self._getIceServerObject(srvid).getUsers()
        for key in userdata:
            if isinstance( userdata[key], str ):
                userdata[key] = userdata[key].decode( "UTF-8" )
        return userdata

    @protectDjangoErrPage
    def getState(self, srvid, sessionid):
        userdata = self._getIceServerObject(srvid).getState(sessionid)
        for key in userdata.__dict__:
            attr = getattr( userdata, key )
            if isinstance( attr, str ):
                setattr( userdata, key, attr.decode( "UTF-8" ) )
        return userdata

    @protectDjangoErrPage
    def registerPlayer(self, srvid, name, email, password):
        # To get the real values of these ENUM entries, try
        # Murmur.UserInfo.UserX.value
        import Murmur
        user = {
            Murmur.UserInfo.UserName:     name.encode( "UTF-8" ),
            Murmur.UserInfo.UserEmail:    email.encode( "UTF-8" ),
            Murmur.UserInfo.UserPassword: password.encode( "UTF-8" ),
            }
        return self._getIceServerObject(srvid).registerUser( user )

    @protectDjangoErrPage
    def unregisterPlayer(self, srvid, mumbleid):
        self._getIceServerObject(srvid).unregisterUser(mumbleid)

    @protectDjangoErrPage
    def getRegistration(self, srvid, mumbleid):
        reg = self._getIceServerObject( srvid ).getRegistration( mumbleid )
        user = ObjectInfo( userid=mumbleid, name="", email="", comment="", hash="", pw="" )
        import Murmur
        if Murmur.UserInfo.UserName    in reg: user.name    = reg[Murmur.UserInfo.UserName]
        if Murmur.UserInfo.UserEmail   in reg: user.email   = reg[Murmur.UserInfo.UserEmail]
        if Murmur.UserInfo.UserComment in reg: user.comment = reg[Murmur.UserInfo.UserComment]
        if Murmur.UserInfo.UserHash    in reg: user.hash    = reg[Murmur.UserInfo.UserHash]
        return user

    @protectDjangoErrPage
    def setRegistration(self, srvid, mumbleid, name, email, password):
        import Murmur
        user = {
            Murmur.UserInfo.UserName:     name.encode( "UTF-8" ),
            Murmur.UserInfo.UserEmail:    email.encode( "UTF-8" ),
            Murmur.UserInfo.UserPassword: password.encode( "UTF-8" ),
            }
        return self._getIceServerObject( srvid ).updateRegistration( mumbleid, user )

    @protectDjangoErrPage
    def getAllConf(self, srvid):
        conf = self.setUnicodeFlag(self._getIceServerObject(srvid).getAllConf())

        info = {}
        for key in conf:
            if key == "playername" and conf[key]:
                # Buggy database transition from 1.1.8 -> 1.2.0
                # Store username as "username" field and set playername field to empty
                info['username'] = conf[key]
                self.setConf( srvid, "playername", "" )
                self.setConf( srvid, "username",   conf[key] )
            else:
                info[str(key)] = conf[key]

        return info

    @protectDjangoErrPage
    def getConf(self, srvid, key):
        return self._getIceServerObject(srvid).getConf( key )

    @protectDjangoErrPage
    def setConf(self, srvid, key, value):
        if value is None:
            value = ''
        self._getIceServerObject(srvid).setConf( key, value.encode( "UTF-8" ) )

    @protectDjangoErrPage
    def getACL(self, srvid, channelid):
        return self._getIceServerObject(srvid).getACL(channelid)

    @protectDjangoErrPage
    def setACL(self, srvid, channelid, acls, groups, inherit):
        return self._getIceServerObject(srvid).setACL( channelid, acls, groups, inherit )

    @protectDjangoErrPage
    def getBans(self, srvid):
        return self._getIceServerObject(srvid).getBans()

    @protectDjangoErrPage
    def setBans(self, srvid, bans):
        return self._getIceServerObject(srvid).setBans(bans)

    @protectDjangoErrPage
    def addBanForSession(self, srvid, sessionid, **kwargs):
        session = self.getState(srvid, sessionid)
        if "bits" not in kwargs:
            kwargs["bits"] = 128
        if "start" not in kwargs:
            kwargs["start"] = int(time())
        if "duration" not in kwargs:
            kwargs["duration"] = 3600
        return self.addBan(srvid, address=session.address, **kwargs)

    @protectDjangoErrPage
    def addBan(self, srvid, **kwargs):
        for key in kwargs:
            if isinstance(kwargs[key], str):
                kwargs[key] = kwargs[key].encode("UTF-8")

        from Murmur import Ban
        srvbans = self.getBans(srvid)
        srvbans.append( Ban( **kwargs ) )
        return self.setBans(srvid, srvbans)

    @protectDjangoErrPage
    def removeBan(self, srvid, **kwargs):
        return self.setBans(srvid, [
            # keep all bans which don't match exactly the one we're looking for
            ban for ban in self.getBans(srvid)
            # if one of those attr checks fails (-> False), min() is False -> keep the thing
            if not min([ getattr(ban, kw) == kwargs[kw] for kw in kwargs ])
            ])

    @protectDjangoErrPage
    def kickUser(self, srvid, userid, reason=""):
        return self._getIceServerObject(srvid).kickUser( userid, reason.encode("UTF-8") )

    @protectDjangoErrPage
    def renameChannel( self, srvid, channelid, name, description ):
        srv = self._getIceServerObject(srvid)
        state = srv.getChannelState(channelid)
        state.name = name.encode("UTF-8")
        state.description = description.encode("UTF-8")
        srv.setChannelState(state)

    @protectDjangoErrPage
    def getUptime(self, srvid):
        return None


class MumbleCtlIce_122(MumbleCtlIce_120):
    @protectDjangoErrPage
    def getTexture(self, srvid, mumbleid):
        raise ValueError( "This method is buggy in 1.2.2, sorry dude." )

    @protectDjangoErrPage
    def setTexture(self, srvid, mumbleid, infile):
        buf = BytesIO()
        infile.save( buf, "PNG" )
        buf.seek(0)
        self._getIceServerObject(srvid).setTexture(mumbleid, buf.read())

    @protectDjangoErrPage
    def getUptime(self, srvid):
        return self._getIceServerObject(srvid).getUptime()


class MumbleCtlIce_123(MumbleCtlIce_120):

    @protectDjangoErrPage
    def getRawTexture(self, srvid, mumbleid):
        return self._getIceServerObject(srvid).getTexture(mumbleid)

    @protectDjangoErrPage
    def getTexture(self, srvid, mumbleid):
        texture = self.getRawTexture(srvid, mumbleid)
        if len(texture) == 0:
            raise ValueError("No Texture has been set.")
        from io import BytesIO
        try:
            return Image.open(BytesIO(texture))
        except IOError as err:
            raise ValueError(err)

    @protectDjangoErrPage
    def setTexture(self, srvid, mumbleid, infile):
        buf = BytesIO()
        infile.save(buf, "PNG")
        buf.seek(0)
        self._getIceServerObject(srvid).setTexture(mumbleid, buf.read())

    @protectDjangoErrPage
    def getUptime(self, srvid):
        return self._getIceServerObject(srvid).getUptime()


class MumbleCtlIce_150(MumbleCtlIce_120):
    """Mumble 1.5+ Ice interface support using MumbleServer slice."""
    def __init__(self, connstring, meta):
        super().__init__(connstring, meta)

    @protectDjangoErrPage
    def getRegisteredPlayers(self, srvid, filter = ''):
        users = self._getIceServerObject(srvid).getRegisteredUsers(filter)
        ret = {}
        for id, name in users.items():
            ret[id] = ObjectInfo(userid=id, name=name, email='', pw='')
        return ret

    @protectDjangoErrPage
    def getPlayers(self, srvid):
        users = self._getIceServerObject(srvid).getUsers()
        ret = {}
        for session, user in users.items():
            ret[session] = ObjectInfo(
                session=user.session,
                userid=user.userid,
                mute=user.mute,
                deaf=user.deaf,
                suppress=user.suppress,
                selfMute=user.selfMute,
                selfDeaf=user.selfDeaf,
                channel=user.channel,
                name=user.name,
                onlinesecs=user.onlinesecs,
                bytespersec=user.bytespersec
            )
        return ret

    @protectDjangoErrPage
    def registerPlayer(self, srvid, name, email, password):
        import MumbleServer
        userinfo = {
            MumbleServer.UserInfo.UserName: name,
            MumbleServer.UserInfo.UserEmail: email,
            MumbleServer.UserInfo.UserPassword: password
        }
        return self._getIceServerObject(srvid).registerUser(userinfo)

    @protectDjangoErrPage
    def unregisterPlayer(self, srvid, userid):
        self._getIceServerObject(srvid).unregisterUser(userid)

    @protectDjangoErrPage
    def getRegistration(self, srvid, userid):
        import MumbleServer
        reg = self._getIceServerObject(srvid).getRegistration(userid)
        user = ObjectInfo(userid=userid, name="", email="", comment="", hash="", pw="")
        if MumbleServer.UserInfo.UserName in reg:
            user.name = reg[MumbleServer.UserInfo.UserName]
        if MumbleServer.UserInfo.UserEmail in reg:
            user.email = reg[MumbleServer.UserInfo.UserEmail]
        if MumbleServer.UserInfo.UserComment in reg:
            user.comment = reg[MumbleServer.UserInfo.UserComment]
        if MumbleServer.UserInfo.UserHash in reg:
            user.hash = reg[MumbleServer.UserInfo.UserHash]
        return user

    @protectDjangoErrPage
    def setRegistration(self, srvid, userid, name, email, password):
        import MumbleServer
        userinfo = {
            MumbleServer.UserInfo.UserName: name,
            MumbleServer.UserInfo.UserEmail: email,
            MumbleServer.UserInfo.UserPassword: password
        }
        return self._getIceServerObject(srvid).updateRegistration(userid, userinfo)

    @protectDjangoErrPage
    def getACL(self, srvid, channelid):
        return self._getIceServerObject(srvid).getACL(channelid)

    @protectDjangoErrPage
    def setACL(self, srvid, channelid, acls, groups, inherit):
        return self._getIceServerObject(srvid).setACL(channelid, acls, groups, inherit)

    @protectDjangoErrPage
    def getBans(self, srvid):
        return self._getIceServerObject(srvid).getBans()

    @protectDjangoErrPage
    def setBans(self, srvid, bans):
        return self._getIceServerObject(srvid).setBans(bans)

    @protectDjangoErrPage
    def getTexture(self, srvid, userid):
        return self._getIceServerObject(srvid).getTexture(userid)

    @protectDjangoErrPage
    def setTexture(self, srvid, userid, infile):
        buf = BytesIO()
        infile.save(buf, "PNG")
        buf.seek(0)
        self._getIceServerObject(srvid).setTexture(userid, buf.read())

    @protectDjangoErrPage
    def getUptime(self, srvid):
        return self._getIceServerObject(srvid).getUptime()


