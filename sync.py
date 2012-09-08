
# this is the magic interpreted by Sonata, referring to on_enable etc. below:

### BEGIN PLUGIN INFO
# [plugin]
# plugin_format: 0, 0
# name: Sync plugin
# version: 0, 0, 1
# description: Allows to add music on USB Mass Storage devices.
# author: Tuukka Hastrup
# author_email: aassfxxxp@hackerzvoice.net
# url: http://aassfxxx.infos.st/
# license: GPL v3 or later
# [capabilities]
# enablables: on_enable
### END PLUGIN INFO

# nothing magical from here on

import gobject, gtk, pango

from sonata.misc import escape_html
import dbus
import os
import re
import gtk
import __main__
import threading
import traceback
import shutil
import sonata.mpdhelper as mpdh

syncmgr = None

# Get audio devices
def get_compatible_devices():
    devices = []
    bus = dbus.SystemBus()
    ud_manager_obj = bus.get_object("org.freedesktop.UDisks", "/org/freedesktop/UDisks")
    ud_manager = dbus.Interface(ud_manager_obj, 'org.freedesktop.UDisks')
    dbus_devices = ud_manager.EnumerateDevices(dbus_interface='org.freedesktop.UDisks')
    for dev in dbus_devices:
        obj =  Device (bus, dev)
        if(obj.is_handleable()):
            devices.append(obj)    
    return devices
    
# Get music path
def parse_is_audio_player(mount_point):
    directories = None
    mount_point = mount_point + "/"
    with open( mount_point + ".is_audio_player", 'r' ) as fh:
        line_re = re.compile( '^\s*(\S+)\s*=\s*(.*)' )
        while 1:
            line = fh.readline()
            if not line: break
            match = line_re.match(line)
            if match:
                if match.group(1) == 'audio_folders':
                    folders = re.findall( '\s*("([^"]+)"|([^,\s]+))\s*', match.group(2) )
                    directories = []
                    for folder in folders:
                        if folder[1]: folder = folder[1]
                        else: folder = folder[2]
                        directories.append( mount_point + folder )
    return directories

#Class which manages devices
class Device:
    def __init__(self, bus, device_path):
        self.bus = bus
        self.device_path = device_path
        self.device = self.bus.get_object('org.freedesktop.UDisks', device_path)

    def __str__(self):
        return self.device_path

    def _get_property(self, property):
        return self.device.Get('org.freedesktop.DBus.Device', property,
                               dbus_interface='org.freedesktop.DBus.Properties')

    def is_systeminternal(self):
        return self._get_property('DeviceIsSystemInternal')

    def is_handleable(self):
        if self.is_filesystem() and not self.is_systeminternal() and self.is_mounted():
            return os.path.isfile(self.mount_paths()[0]+"/.is_audio_player")
        else:
            return False

    def is_mounted(self):
        return self._get_property('DeviceIsMounted')

    def mount_paths(self):
        raw_paths = self._get_property('DeviceMountPaths')
        return raw_paths
        
    def device_file(self):
        return self._get_property('DeviceFile')
        
    def is_filesystem(self):
        return self._get_property('IdUsage') == 'filesystem'

    def has_media(self):
        return self._get_property('DeviceIsMediaAvailable')

#Main class of the plugin
class SyncManager:
    def __init__(self, UIManager, app):
        # installs UI manager
        self.UIManager = UIManager
        self.app = app
        self.config = app.config
        self.menu_obj = None
        self.actionGroup = None
        self.syncActionGroup = gtk.ActionGroup("MPDSynchroMenu")
        actions = [("syncmenu", None, _("Send to device")),
                   ("reloadsync", None, _("Reload devices list"), None, None, self.on_reload_menu_click)]
        self.syncActionGroup.add_actions(actions)
        self.UIManager().insert_action_group(self.syncActionGroup)
        
        self.populate_menus()
        
    def populate_menus(self):
        self.remove_menus()
        self.actionGroup = gtk.ActionGroup('MPDSynchro')
        self.devices = get_compatible_devices()
        self.UIManager().ensure_update()
        actions = [('%s' % parse_is_audio_player(device.mount_paths()[0])[0],
                gtk.STOCK_CONNECT,
                device._get_property('IdLabel').replace('&', ''), None, None,
                self.on_device_menu_click)
                for device in self.devices]
        self.actionGroup.add_actions(actions)
        uiDescription = """
            <ui>
              <popup name="mainmenu">
                  <menu action="syncmenu">
                    <menuitem action=\"reloadsync\"/>
        """
        uiDescription += ''.join('<menuitem action=\"%s\"/>' % action[0]
                        for action in actions)
        uiDescription += '</menu></popup></ui>'
        self.menu_obj = self.UIManager().add_ui_from_string(uiDescription)
        self.UIManager().insert_action_group(self.actionGroup, 0)
        self.UIManager().get_widget('/hidden').set_property('visible', False)
        
    def remove_menus(self):
        if self.menu_obj:
            self.UIManager().remove_ui(self.menu_obj)
            self.menu_obj = None
        if self.actionGroup:
            self.UIManager().remove_action_group(self.actionGroup)
            self.actionGroup = None

    def on_device_menu_click(self, action):
        #print action.get_name()
        # Gets files list
        if self.app.current_tab == self.app.TAB_LIBRARY:
            songs = self.app.library.get_path_child_filenames(True)
        elif self.app.current_tab == self.app.TAB_CURRENT:
            songs = self.app.current.get_selected_filenames(0)
        
       
        for song in songs:
            # Get metadata for song
            self.search_result = mpdh.call(self.app.client, 'search',
                        "file", song)[0]
            artist = _("Unknown")
            album = _("Unknown")
            track = 0
            filename = os.path.basename(song)
            filePrefix, fileExtension = os.path.splitext(filename)
            print filename
            if "artist" in self.search_result:
                artist = self.search_result["artist"].replace("/", "-")
            if "album" in self.search_result:
                album = self.search_result["album"].replace("/", "-")
            if "track" in self.search_result:
                track = self.search_result["track"]
            if "title" in self.search_result:
                filename = self.search_result["title"] + fileExtension
            outpath = os.path.join(action.get_name(), artist, album)
            # Create directory if not exists
            if not os.path.isdir(outpath):
                os.makedirs(outpath)
            else:
                print "Directory exists"
            # Let's check & copy file if needed
            numtrack = "%02d" % track           
            outfile = os.path.join(outpath, numtrack + " - " + filename)
            if not os.path.isfile(outfile):
                srcfile = os.path.join(self.config.musicdir[self.config.profile_num], self.search_result["file"])
                shutil.copyfile(srcfile, outfile)
            else:
                print "File exists"
                
    def on_reload_menu_click(self, action):
        self.populate_menus()
    
# this gets called when the plugin is loaded, enabled, or disabled:
def on_enable(state):
    global devices
    if state:
        # Let's do ugly things due to weakness of plugin system design
        grab_ui_manager()
    else:
        syncmgr.remove_menus()
        
# Monkey code to grab the UI Manager
def grab_ui_manager():
    global syncmgr
    try:
        UIManager = __main__.app.UIManager
        try:
            if not syncmgr:
                syncmgr = SyncManager(lambda:UIManager, __main__.app)
            else:
                syncmgr.populate_menus()
        except Exception:
            traceback.print_exc()
    except Exception:
        t = threading.Timer(0.2, grab_ui_manager)
        t.start()

