#!/usr/bin/python3

from bluepy import btle
import argparse
import os
import re
from dataclasses import dataclass
from collections import deque
import threading
import time
import signal
import traceback
import logging


@dataclass
class Measurement:
    temperature: float
    humidity: int
    voltage: float
    battery: int = 0
    timestamp: int = 0

    def __eq__(self, other):
        if self.temperature == other.temperature and self.humidity == other.humidity and self.battery == other.battery and self.voltage == other.voltage:
            return  True
        else:
            return False


measurements = deque()


def signal_handler(sig, frame):
        os._exit(0)


def watchDog_Thread():
    global unconnectedTime
    global connected
    global pid
    while True:
        logging.debug("watchdog_Thread")
        logging.debug("unconnectedTime : " + str(unconnectedTime))
        logging.debug("connected : " + str(connected))
        logging.debug("pid : " + str(pid))
        now = int(time.time())
        if (unconnectedTime is not None) and ((now - unconnectedTime) > 60): #could also check connected is False, but this is more fault proof
            pstree=os.popen("pstree -p " + str(pid)).read() #we want to kill only bluepy from our own process tree, because other python scripts have there own bluepy-helper process
            logging.debug("PSTree: " + pstree)
            try:
                bluepypid=re.findall(r'bluepy-helper\((.*)\)',pstree)[0] #Store the bluepypid, to kill it later
            except IndexError: #Should not happen since we're now connected
                logging.debug("Couldn't find pid of bluepy-helper")
            os.system("kill " + bluepypid)
            logging.debug("Killed bluepy with pid: " + str(bluepypid))
            unconnectedTime = now #reset unconnectedTime to prevent multiple killings in a row
        time.sleep(5)



class MyDelegate(btle.DefaultDelegate):
    def __init__(self, params):
        btle.DefaultDelegate.__init__(self)
        # ... initialise here

    def handleNotification(self, cHandle, data):
        global measurements
        try:
            measurement = Measurement(0, 0, 0, 0, 0)
            measurement.timestamp = int(time.time())
            temp=int.from_bytes(data[0:2],byteorder='little',signed=True)/100
            print("Temperature: " + str(temp))

            humidity=int.from_bytes(data[2:3],byteorder='little')
            print("Humidity: " + str(humidity))

            voltage=int.from_bytes(data[3:5],byteorder='little') / 1000.
            print("Battery voltage:",voltage)
            measurement.temperature = temp
            measurement.humidity = humidity
            measurement.voltage = voltage
            if args.battery:
                batteryLevel = min(int(round((voltage - 2.1),2) * 100), 100) #3.1 or above --> 100% 2.1 --> 0 %
                measurement.battery = batteryLevel
                print("Battery level:",batteryLevel)

            measurements.append(measurement)

        except Exception as e:
            print("Fehler")
            print(e)
            print(traceback.format_exc())

# Initialisation  -------

def connect():
    p = btle.Peripheral(adress)    
    val=b'\x01\x00'
    p.writeCharacteristic(0x0038,val,True) #enable notifications of Temperature, Humidity and Battery voltage
    p.writeCharacteristic(0x0046,b'\xf4\x01\x00',True)
    p.withDelegate(MyDelegate("abc"))
    return p

# roll around to the next device address    
def set_address():
    global address_ctr, addresses, adress
    address_ctr += 1
    if address_ctr > len(addresses):
        address_ctr = 0    
    adress = addresses[address_ctr]

# Main loop --------
parser=argparse.ArgumentParser()
parser.add_argument("--device","-d", help="Set the device MAC-Address in format AA:BB:CC:DD:EE:FF",metavar='AA:BB:CC:DD:EE:FF')
parser.add_argument("--battery","-b", help="Get estimated battery level", metavar='', type=int, nargs='?', const=1)
parser.add_argument("--count","-c", help="Read/Receive N measurements and then exit script", metavar='N', type=int)
parser.add_argument("--delay","-del", help="Delay between taking readings from each device", metavar='N', type=int)


args=parser.parse_args()
if args.device:
    print('args.device', args.device)
    addresses = args.device.split(',')
    print(addresses, len(addresses))
    for address in addresses:
        if not re.match("[0-9a-fA-F]{2}([:]?)[0-9a-fA-F]{2}(\\1[0-9a-fA-F]{2}){4}$",address):
            print("Please specify device MAC-Address in format AA:BB:CC:DD:EE:FF")
            os._exit(1)
    address_ctr = 1000
    set_address()

else:
    parser.print_help()
    os._exit(1)


if args.delay:
    delay = args.delay
    print ('Delay set to {} seconds'.format(delay))
else:
    delay = 30
    print ('No delay set. Defaulting to 30 seconds')


p=btle.Peripheral()
cnt=0

signal.signal(signal.SIGINT, signal_handler)
connected=False
#logging.basicConfig(level=logging.DEBUG)
logging.basicConfig(level=logging.ERROR)
logging.debug("Debug: Starting script...")
pid=os.getpid()    
bluepypid=None
unconnectedTime=None

watchdogThread = threading.Thread(target=watchDog_Thread)
watchdogThread.start()
logging.debug("watchdogThread startet")


while len(measurements) < len(addresses):
    try:
        if not connected:
            print("Trying to connect to " + adress)
            p=connect()
            connected=True
            unconnectedTime=None

        if p.waitForNotifications(2000):
            cnt += 1
            if args.count is not None and cnt >= args.count:
                print(str(args.count) + " measurements collected. Exiting in a moment.")
                p.disconnect()
                time.sleep(5)
                #It seems that sometimes bluepy-helper remains and thus prevents a reconnection, so we try killing our own bluepy-helper
                pstree=os.popen("pstree -p " + str(pid)).read() #we want to kill only bluepy from our own process tree, because other python scripts have there own bluepy-helper process
                bluepypid=0
                try:
                    bluepypid=re.findall(r'bluepy-helper\((.*)\)',pstree)[0] #Store the bluepypid, to kill it later
                except IndexError: #Should normally occur because we're disconnected
                    logging.debug("Couldn't find pid of bluepy-helper")
                if bluepypid is not 0:
                    os.system("kill " + bluepypid)
                    logging.debug("Killed bluepy with pid: " + str(bluepypid))
                cnt = 0         # reset the counter - do not exit
                # measurements.clear()            # clear the measurements array or it will continue to grow
                set_address()                   # roll round to the next address in the array
                time.sleep(delay)               # delay between reading each device
            print("")
            continue
    except Exception as e:
        print("Connection lost")
        if connected is True: #First connection abort after connected
            unconnectedTime=int(time.time())
            connected=False
        time.sleep(1)
        logging.debug(e)
        logging.debug(traceback.format_exc())        
        
    print ("Waiting...")
    # Perhaps do something else here
