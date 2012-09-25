#!/usr/bin/python
# -*- coding: utf-8 -*-


import sys
import optparse
import subprocess
import time
import random
import os.path
import logging
import re
import datetime
import socket
import errno


BACKUP_STATUS_PLIST = "/Library/Preferences/DAFGUBackupStatus.plist"
FILTER_FILE = os.path.join(os.path.dirname(__file__), "dafgu_filter.txt")

TEST_HOST = "backupserver.example.com"

STATUS_MENU_PLIST = "/tmp/DAFGUMigrationStatus.plist"
STATUS_UNKNOWN  = 0
STATUS_OK       = 1
STATUS_ERROR    = 2
STATUS_ACTIVE   = 3

SOCKET_DIR = "/tmp"
SOCKET_NAME = "se.gu.it.dafgu_migration_status"


from Foundation import NSData, \
                       NSPropertyListSerialization, \
                       NSPropertyListMutableContainers, \
                       NSPropertyListXMLFormat_v1_0

                       
class FoundationPlistException(Exception):
    pass

class NSPropertyListSerializationException(FoundationPlistException):
    pass
    
class NSPropertyListWriteException(FoundationPlistException):
    pass

def serializePlist(data):
    plistData, error = NSPropertyListSerialization.dataFromPropertyList_format_errorDescription_(
        data, NSPropertyListXMLFormat_v1_0, None)
    if error:
        raise NSPropertyListSerializationException(error)
    return plistData

def writePlist(data, path):
    plistData = serializePlist(data)
    if not plistData.writeToFile_atomically_(path, True):
        raise NSPropertyListWriteException("Failed to write plist data to %s" % path)

def readPlist(path):
    plistData = NSData.dataWithContentsOfFile_(path)
    dataObject, plistFormat, error = \
        NSPropertyListSerialization.propertyListFromData_mutabilityOption_format_errorDescription_(
        plistData, NSPropertyListMutableContainers, None, None)
    if error:
        errmsg = "%s in file %s" % (error, path)
        raise NSPropertyListSerializationException(errmsg)
    else:
        return dataObject


status_socket = None

def set_status_menu(status, message):
    global status_socket
    try:
        writePlist({
            "DAFGUMigrationStatus": status,
            "DAFGUMigrationMessage": message,
        }, STATUS_MENU_PLIST)
    except BaseException, e:
        logging.warn("Writing to %s failed: %s" % (STATUS_MENU_PLIST, e))
    
    try:
        if status_socket is None:
            status_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        if status_socket is not None:
            message = serializePlist({
                "DAFGUMigrationStatus": status,
                "DAFGUMigrationMessage": message,
            })
            for item in os.listdir(SOCKET_DIR):
                if item.startswith(SOCKET_NAME):
                    socket_path = os.path.join(SOCKET_DIR, item)
                    logging.debug("Sending message to %s" % socket_path)
                    try:
                        status_socket.sendto(message, socket_path)
                    except socket.error, e:
                        if e[0] == errno.ECONNREFUSED:
                            logging.info("Removing stale socket %s" % socket_path)
                            os.unlink(socket_path)
                        else:
                            logging.warn("Sending to %s failed: %s" % (socket_path, e))
    except BaseException, e:
        logging.debug("Unhandled exception when updating status menu: %s" % e)
    

def get_status_menu():
    try:
        status = readPlist(STATUS_MENU_PLIST)
        return (status["DAFGUMigrationStatus"], status["DAFGUMigrationMessage"])
    except:
        return (None, None)
    

def route(cmd, *opts):
    """Python wrapper for /sbin/route command."""
    p = subprocess.Popen(["/sbin/route",
                          cmd] + list(opts),
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    out, err = p.communicate()
    return out


re_interface = re.compile(r'^\s*interface: (?P<dev>.+)$')

def get_route_dev(host):
    """Find which network interface access to 'host' is routed through."""
    for line in route("get", host).splitlines():
        m = re_interface.search(line)
        if m:
            logging.debug(u"Found route to %s through %s" % (host, m.group("dev")))
            return m.group("dev")
    else:
        return None
    

def networksetup(cmd, *opts):
    """Python wrapper for /usr/sbin/networksetup command."""
    p = subprocess.Popen(["/usr/sbin/networksetup",
                          "-" + cmd] + list(opts),
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    out, err = p.communicate()
    return out
    

re_srv = re.compile(r'^\([0-9*]+\) (?P<srv>.+)$')
re_port_dev = re.compile(r'^\(Hardware Port: (?P<port>.+), Device: (?P<dev>.*)\)$')
re_info = re.compile(r'^(?P<key>[^:]+): (?P<value>.*)$')
re_cur_net = re.compile(r'^Current \S+ Network: (?P<name>)$')

def get_devices():
    """Generate a list of network device dictionaries."""
    
    devices = list()
    for line in networksetup("listnetworkserviceorder").splitlines():
        m = re_srv.search(line)
        if m:
            srv = m.group("srv")
        m = re_port_dev.search(line)
        if m:
            logging.debug(u"Found network service %s" % srv)
            devices.append({
                "srv": srv,
                "port": m.group("port") if m.group("port") else None,
                "dev": m.group("dev") if m.group("dev") else None,
            })
    
    for dev in devices:
        if dev["srv"]:
            for line in networksetup("getinfo", dev["srv"]).splitlines():
                m = re_info.search(line)
                if m:
                    dev[m.group("key")] = m.group("value") if m.group("value") != "none" else None
    
    return dict([(dev["dev"], dev) for dev in devices])
    

def check_device_class(host):
    """Check what class of network interface is used to access 'host'."""
    
    dev = get_route_dev(host)
    if not dev:
        logging.warn(u"No route to %s" % host)
        return "unknown"
    
    devices = get_devices()
    if dev not in devices:
        logging.warn(u"Failed to get information for %s" % dev)
        return "unknown"
    
    for name, matchre in (
        ("ethernet", re.compile(r'ethernet', re.I)),
        ("wifi", re.compile(r'(wi-fi|airport)', re.I)),
    ):
        if matchre.search(devices[dev]["port"]):
            return name
    else:
        return "unknown"
    

def parse_session_statistics(text):
    stats = dict()
    
    for line in text.split("\n"):
        try:
            key, value = line.split(": ", 1)
            stats[key] = value
        except ValueError:
            pass
    
    return stats
    

def wash_returncode(returncode):
    """Ignore certain error codes."""
    
    if returncode == 24:
        # Partial transfer due to vanished source files
        return 0
    else:
        return returncode
    

def run_backup(source_dir, dest_dir):
    backup_cmd = (u"/usr/local/bin/rsync3",
                  u"--iconv=UTF-8-MAC,UTF-8",
                  u"--recursive",
                  u"--links",
                  u"--times",
                  u"--executability",
                  u"--compress",
                  u"--stats",
                  u"--partial-dir=.rsync-partial",
                  u"--filter=merge %s" % FILTER_FILE,
                  u"--delete-after",
                  u"--delete-excluded",
                  u"--ignore-errors",
                  u"--timeout=300",
                  u"--rsh=ssh -c blowfish-cbc -p 2202",
                  source_dir.encode("utf-8"),
                  dest_dir.encode("utf-8"))
    logging.debug(u" ".join(backup_cmd))
    p = subprocess.Popen(backup_cmd,
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    (stdout, stderr) = p.communicate()
    
    now = time.time()
    
    result_dict = {
        "last_run": now,
        "returncode": wash_returncode(p.returncode),
        "stdout": stdout.decode("utf-8", "ignore"),
        "stderr": stderr.decode("utf-8", "ignore"),
    }
    result_dict.update(parse_session_statistics(result_dict["stdout"]))
    
    return result_dict


def main(argv):
    p = optparse.OptionParser()
    p.set_usage("""Usage: %prog [options] source_dir dest_dir""")
    p.add_option("-v", "--verbose", action="store_true")
    p.add_option("-d", "--randomdelay", type="int", dest="randomdelay")
    options, argv = p.parse_args(argv)
    if len(argv) != 3:
        print >>sys.stderr, p.get_usage()
        return 1
    
    source_dir = argv[1].decode("utf-8")
    dest_dir = argv[2].decode("utf-8")
    
    if options.verbose:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO
    logging.basicConfig( \
        level=log_level, \
        format="%(asctime)s %(filename)s[%(process)d]: %(message)s" \
    )
    
    (status, message) = get_status_menu()
    if status == STATUS_ACTIVE:
        set_status_menu(STATUS_ERROR, u"Last backup interrupted")
    elif status in (STATUS_OK, STATUS_ERROR):
        set_status_menu(status, message)
    else:
        set_status_menu(STATUS_UNKNOWN, u"Waiting for network…")
    
    if not os.path.exists(BACKUP_STATUS_PLIST):
        logging.warn(u"No previous backup run found, initializing first backup")
        options.verbose = True
        logging.info(u"Sleeping for 30 seconds")
        time.sleep(30)
    elif options.randomdelay:
        sleep_time = random.randrange(0, options.randomdelay)
        logging.info(u"Sleeping for %d seconds" % sleep_time)
        time.sleep(sleep_time)
    
    set_status_menu(STATUS_ACTIVE, u"Checking network…")
    
    logging.debug(u"Checking network class...")
    net_class = check_device_class(TEST_HOST)
    logging.info(u"Network is '%s'" % net_class)
    if net_class != "ethernet":
        logging.warn(u"Aborting migration backup as network isn't ethernet")
        (status, message) = get_status_menu()
        set_status_menu(status, message)
        return 0
    
    set_status_menu(STATUS_ACTIVE, u"Running backup…")
    
    logging.info(u"Backing up %s to %s".encode("utf-8") % (source_dir, dest_dir))
    status_dict = run_backup(source_dir, dest_dir)
    logging.info(u"Backup finished with return code %d" % status_dict["returncode"])
    
    set_status_menu(STATUS_ACTIVE, u"Finishing…")
    
    logging.debug(u"Saving status to %s".encode("utf-8") % BACKUP_STATUS_PLIST)
    writePlist(status_dict, BACKUP_STATUS_PLIST)
    
    dt = datetime.datetime.fromtimestamp(status_dict["last_run"])
    if status_dict["returncode"] == 0:
        set_status_menu(STATUS_OK, dt.strftime("%Y-%m-%d %H:%M"))
    else:
        set_status_menu(STATUS_ERROR, u"Backup failed")
    
    logging.debug(u"Done.")
    
    return 0
    

if __name__ == '__main__':
    sys.exit(main(sys.argv))
    
