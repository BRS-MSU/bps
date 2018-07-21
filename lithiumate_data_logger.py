#!/usr/bin/env python

# Lithiumate Touch-Screen Display
# Copyright Elithion Inc 2017
# Based on "Lithiumate WiFi", rev Jul 2 2013, started Mar/17/2013
# Started Jun 30th 2017, Davide Andrea
# Rev Jul 3 2017

#IMPORT
from contextlib import closing
import grp
import json
import os
import pickle
import pwd
import re
import requests
import subprocess
import sys
import serial
import termios
import threading
import time
import urllib
import urllib2





# CONSTANTS
# Serial port
DEFAULT_PORT = '/dev/ttyUSB0'
DEFAULT_BAUDRATE = 57600
DEFAULT_PARITY = 'N'
DEFAULT_XONXOFF = False
DEFAULT_RTSCTS = False

# Codes to request data from BMS
POWER_CHAR = b'p'
CONSTANTS_CHAR = b'q'
SETTINGS_CHAR = b's'
VARIABLES_CHAR = b'x'
VOLTAGES_CHAR = b'v'
TEMPERATURES_CHAR = b't'
RESISTANCES_CHAR = b'r'
DISPLAY_SN_CHAR = b'n'
ALL_CHARS = (POWER_CHAR,CONSTANTS_CHAR,SETTINGS_CHAR,VARIABLES_CHAR,VOLTAGES_CHAR,TEMPERATURES_CHAR,RESISTANCES_CHAR,DISPLAY_SN_CHAR)
BMS_CHARS = (DISPLAY_SN_CHAR,POWER_CHAR,CONSTANTS_CHAR,SETTINGS_CHAR,VARIABLES_CHAR,VOLTAGES_CHAR,TEMPERATURES_CHAR,RESISTANCES_CHAR)
SEC_REQ_CHARS = (VOLTAGES_CHAR,TEMPERATURES_CHAR,RESISTANCES_CHAR)

# Codes for the power status
BOOTLEG_COPY = '0'
USB_DISCONNECTED = '1'
BMS_OFF = '2'
BMS_ON = '3'

# Misc
REQ_DLY = 0.3 # seconds
SHOW_OUT = False # Show progress in io out or log file
SHOW_DATA = False # Include read data in shown data
LOG_OUT = False # True # Log data in a file instead of showing it
CTR_FILE = '/home/pi/Elithion/ctrl.txt'
MEDIA_DIR = '/media/pi'

OUT_DATA_START = '''<!DOCTYPE HTML>
<html lang="en-us">
'''

OUT_DATA_END = '</html>'


# Paths
HOME_DIR_PATH = '/home/pi/Elithion/'
STATIC_DIR_PATH = '/home/pi/Elithion/static/'
VALIDATION_FILE = HOME_DIR_PATH + '.sn'
LOG_FILE_PATH = HOME_DIR_PATH + 'lithiumateLog.txt'
BMS_DATA_PATH = STATIC_DIR_PATH + 'lithiumatedata.html'
BMS_DATA_TMP_PATH = STATIC_DIR_PATH + 'lithiumatedata.tmp'

# Global variables
intClock = 0
rxData = '' # Buffer for received data
dataDict = {} # Dictionary for the data received
portOpen = False
reqChar = ''
thisSerialNumber = ''
serialPort = None
dataLogFile = None

#LithiumateDataLogger CLASS



def clearData():
	"""Clear the data dictionary"""
	global dataDict
	for secReqCharNo in range(len(ALL_CHARS)):
		dataDict[ALL_CHARS[secReqCharNo]] = ''


def mainLoop():
	"""Main loop"""
	
	# Local variables
	varsTurn = True
	secReqCharCtr = 0 # Secondary character counter

	# Globals
	global intClock
	global dataDict
	global reqChar
	
	while True:
		# If the port is closed, try opening it
		if not portOpen:
			openPort()

		# Select which data we'll request
		if dataDict[CONSTANTS_CHAR] == '': # If we didn't get the Constants (done only once)
			reqChar = CONSTANTS_CHAR # Get the Constants
		elif dataDict[SETTINGS_CHAR] == '': # If we didn't get the Settings (done only once)
			reqChar = SETTINGS_CHAR  # Get the Settings
		elif varsTurn: # If time to get the variables
			reqChar = VARIABLES_CHAR # Get the variables
		else: # If time to get a secondary item
			secReqCharCtr = (secReqCharCtr + 1) % len(SEC_REQ_CHARS) # Go to the next secondary request character
			reqChar = SEC_REQ_CHARS[secReqCharCtr] # Get the secondary item
		varsTurn = not varsTurn # Toggle between variables and secondary items

		# Request data from the BMS
		if portOpen:
			reqData()

		# Sleep to set the TX timing (and give time to receive the data)
		time.sleep(REQ_DLY)

		# Get Raspberry Pi data
		getPiData()

		# Receive and parse the data
		if portOpen:
			getData()
		if portOpen:
			parseData()
		
		# If enabled, send the data to the Elithion server
		if getCtrls('remoteEnab'):
			postToServer()
			
		

	
def getCtrls(ctrlKey):
	"""Get a coltrol item (stored in a file)"""

	# Control is asynchronous
	# Receive a key for the dictionary
	# Read the control dictionary from a file, so that it's accessible to all threads, regardless how they were started
	# Extract the dictionary, take the requested item and return the control request
	ctrlItem = None
	ctrlDict = {}
	try:
		with open(CTR_FILE, 'rb') as ctrlFile:
			ctrlDict = pickle.load(ctrlFile)
		ctrlItem = ctrlDict[ctrlKey]
	except:
		pass
	return ctrlItem


def postToServer():
	"""Post BMS data to the Elithion server"""
	
	# Globals
	global portOpen
	
	# Constants
	ContentTypeKey = 'Content-Type'
	ContentTypeVal = 'application/json'
	# ContentTypeVal = 'application/x-www-form-urlencoded'
	ElithionWriteScriptURL = 'http://elithion.com/cgi-bin/rmwr.py'
		
	try:
		# Make a new dictionary just with the BMS data and the ID of this display
		bmsDataDict = {}
		for indexChar in BMS_CHARS:
			bmsDataDict[indexChar] = dataDict[indexChar]
	
		# Convert it to JSON string
		jsonParams = json.dumps(bmsDataDict)
	
		# Post it to the server's script
		urlReq = urllib2.Request(ElithionWriteScriptURL)
		urlReq.add_data(jsonParams)
		urlReq.add_header(ContentTypeKey, ContentTypeVal)
		urlFile = urllib2.urlopen(urlReq)
		postResponse = urlFile.read()
		print urlReq.get_full_url(), postResponse.strip()
		urlFile.close()
	except:
		pass

def reqData():
	"""Request data from the BMS"""
	logEvent(reqChar)
	# Send the request character and enable reception
	try:
		serialPort.flushInput() # Clear the receive buffer
		serialPort.write(reqChar) # Send the request character
	except:
		portOpen = False


def getData():
	"""Get received data"""
	# Globals
	global portOpen
	global rxData
	
	try:
		rxData = serialPort.read(serialPort.inWaiting()) # Reads the entire available data
		if SHOW_DATA: logEvent('\n('+ rxData +')')
	except:
		portOpen = False

def getPiData():
	"""Get Raspberry Pi data"""
	dataDict[DISPLAY_SN_CHAR] = thisSerialNumber.upper()
		
		
def parseData():
	"""Parse the received data"""
	global rxData
	# If no response, report tha the BMS power is off (the USB is connected)
	if rxData == '':
		logEvent('0ff')
		clearData() # Clear the data dictionary
		dataDict[POWER_CHAR] = BMS_OFF
		saveData() # Save all data to the output HTML file
	# There was a response: flag that the BMS is on, validate the response and save it
	else:
		dataDict[POWER_CHAR] = BMS_ON
		startPos = rxData.find('|' + reqChar) # Find the start of the data string
		if startPos >= 0: # If found
			rxData = rxData[startPos+2:] # Remove any characters before the start of the data string
			endPos = rxData.find('|') # Find the end of the data string
			if endPos >= 0: # If found
				rxData = rxData[:endPos] # Remove any characters beyond it
				# Now we have the complete record for the secondary data
				noOfChars = len(rxData) # Get the number of characters
				noOfDataBytes = int(rxData[:2],16) # Extract the number of data bytes
				# Check the number of characters is we were told to expect
				if noOfChars == 2 * (noOfDataBytes + 2): # If the correct number of characters; 2 characters per hex byte, an extra byte for the length, an extra for the checksum
					# Check the checksum
					checkSum = 0
					for byteNo in range(noOfChars/2): # For each byte (2 characters)
						checkSum +=  int(rxData[2*byteNo:2*byteNo+2],16) # Add it to the checksum
					if checkSum  % 256 == 0: # If the checksum is OK
						dataDict[reqChar] = rxData # Store these data in the dictionary
						saveData() # Save all data to the output HTML file



def saveData():
	"""Save all data to the output HTML file"""
	global intClock
	outDataStr = OUT_DATA_START
	for secReqCharNo in range(len(ALL_CHARS)):
		secReqChar = ALL_CHARS[secReqCharNo]
		if secReqChar in dataDict:
			outDataStr += secReqChar + "='" + dataDict[secReqChar] + "';\n"
	outDataStr += 'c=\'' + str(intClock) +'\';\n'
	outDataStr += OUT_DATA_END
	intClock = (intClock + 1) %10000
	try:
		dataFile = open(BMS_DATA_TMP_PATH,'w')
		dataFile.write(outDataStr)
		dataFile.flush()
		dataFile.close()
		os.rename(BMS_DATA_TMP_PATH,BMS_DATA_PATH)
	except:
		logEvent('Failed to write data file')


def validateInstall():
	"""Validate the install"""
	# Globals
	global thisSerialNumber
	
	# Get the serial number of this hardware
	thisSerialNumber = ''
	cupInfoFile = open('/proc/cpuinfo', 'r')
	cupInfoLines =  cupInfoFile.readlines()
	for aLine in cupInfoLines:
		if 'Serial' in aLine:
			thisSerialNumber = aLine.split(':')[1].strip()
	cupInfoFile.close()
	# If we already had a serial number, check it
	logEvent(' hrdwr sn:' + thisSerialNumber)
	if os.path.exists(VALIDATION_FILE):
		origSnFile = open(VALIDATION_FILE, 'r')
		origSerialNumber = origSnFile.read().strip()
		logEvent(' stored sn:' + origSerialNumber)
		if origSerialNumber != thisSerialNumber:
			dataDict[POWER_CHAR] = BOOTLEG_COPY
			saveData()
			logEvent(' Bootleg copy: shutting down.')
			return False
	# If we didn't yet have a serial number, save it
	else:
		logEvent('save new serial number ')
		origSnFile = open(VALIDATION_FILE, 'w')
		origSnFile.write(thisSerialNumber)
	origSnFile.close()
	# Save the serial number as the login for remote access of data
	return True

def logEvent(logText):
	"""Log or write data"""
	if SHOW_OUT:
			sys.stdout.write(logText)
			sys.stdout.flush()


def openPort():
	"""If the port is closed, try to open it"""
	# Globals
	global portOpen
	global serialPort
	
	# If the port is closed, try opening it
	try:
		# Open the port
		logEvent('o')
		# THIS NEXT LINE HANGS-UP THE COMPUTER WITH FTDI DONGLES THAT USE AN FT232B chip. It works fine with a FT232R chip
		serialPort = serial.serial_for_url(DEFAULT_PORT, DEFAULT_BAUDRATE, parity=DEFAULT_PARITY, rtscts=DEFAULT_RTSCTS, xonxoff=DEFAULT_XONXOFF, timeout=1)
		portOpen = True # Flag that the port is open
		logEvent('O')
	except serial.SerialException as e:
		logEvent('_')
		# Unable to open the port: report that the USB is disconnected
		clearData() # Clear the data dictionary
		dataDict[POWER_CHAR] = USB_DISCONNECTED
		saveData() # Save all data to the output HTML file
		# Try to help recovery of the USB port with the following
		try:
			serialPort.close()
		except:
			pass
		time.sleep(1)
		logEvent('_')


# GET AND POST HANDLER

def getWiFiList():
	"""Service a GET from the HTML page to get a list of WiFi networks"""
	
	# Locals
	GET_ACTV_NET_CMD = 'sudo iwgetid'
	GET_NET_LIST_CMD = 'sudo iw dev wlan0 scan'

	wifiNetworkList = ''
	# Presently connected network
	connectedNetworkNameResponse = doLinuxCmd(GET_ACTV_NET_CMD)
	if connectedNetworkNameResponse:
		connectedNetworkNameList = re.findall('\"(.*?)\"', connectedNetworkNameResponse) #" Find the string between quotes
		wifiNetworkList = connectedNetworkNameList[0] # [0] returns the first one
	
	# Available networks
	availableNetworksResponse = doLinuxCmd(GET_NET_LIST_CMD)
	if availableNetworksResponse :
		availableNetworksLines = availableNetworksResponse.split('\n')
		for availableNetworksLine in availableNetworksLines:
			if 'SSID' in availableNetworksLine:
				# Extract the SSID of the network
				# Typical line:
				#	\tSSID: elithion belkin
				essid = availableNetworksLine.replace('SSID:','').strip()
				wifiNetworkList = wifiNetworkList + ',' + essid 
	
	return wifiNetworkList


def postWiFiSrvc(wiFiNet, wiFiPassword):
	"""Service a POST from the HTML page to select the WiFi network"""
	
	# Locals
	WIFI_LOGIN_FILE = '/etc/wpa_supplicant/wpa_supplicant.conf'
	WIFI_LOGIN_TMP_FILE_PATH = 'wpa_supplicant.tmp'
	WIFI_LOGIN_FILE_PATH = '/etc/wpa_supplicant/wpa_supplicant.conf'
	STOP_WIFI_TIME = 2 # seconds
	RESTART_WIFI_TIME = 2 # seconds
	WIFI_LOGIN_FILE_TXT = """ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=US

network={
	ssid="%s"
	psk="%s"
	key_mgmt=WPA-PSK
}
"""
	WIFI_LOGIN_FILE_NONE_TXT = """ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=US
"""
	ReplaceFileCmd = 'sudo mv -f %s %s' % (WIFI_LOGIN_TMP_FILE_PATH, WIFI_LOGIN_FILE_PATH)
	KILL_WIFI_CMD = 'sudo pkill wpa_supplicant'
	START_WIFI_CMD = 'sudo wpa_supplicant -i wlan0 -c /etc/wpa_supplicant/wpa_supplicant.conf -B'
	CHANGE_OWNER_CMD = 'sudo chown root %s' % WIFI_LOGIN_TMP_FILE_PATH
	CHANGE_GROUP_CMD = 'sudo chown :root %s' % WIFI_LOGIN_TMP_FILE_PATH

	# Write a temporary WiFi configuration page
	logInFile = open(WIFI_LOGIN_TMP_FILE_PATH,'w')
	if wiFiNet == '':
		logInFile.write(WIFI_LOGIN_FILE_NONE_TXT)
	else:
		logInFile.write(WIFI_LOGIN_FILE_TXT % (wiFiNet, wiFiPassword))
	logInFile.close()
	time.sleep(STOP_WIFI_TIME)

	# Change its ownership and group to root
	doLinuxCmd(CHANGE_OWNER_CMD)
	doLinuxCmd(CHANGE_GROUP_CMD)
	
	# Replace the actual WiFi config file with the temporary one
	doLinuxCmd(ReplaceFileCmd)
	time.sleep(STOP_WIFI_TIME)

	# Restart the WiFi
	# ifdown / ifup does not recognize wlan0
	# sudo ifconfig wlan0 down / up simply turns off and on WiFi connectivity,
	#   but the contents of the wpa_supplicant.config file are ignored
	# sudo service networking restart doesn't do squat
	# So all we can do is kill the prcess and restart it
	#   (short of actually restarting the Pi)
	#doLinuxCmd(KILL_WIFI_CMD)
	#time.sleep(RESTART_WIFI_TIME)
	#doLinuxCmd(START_WIFI_CMD)
	
	return 'OK wifi'


def postControlSrvc(ctrlDictJson):
	"""Service a POST from the HTML page to control the Pi"""
	
	# Control is asynchronous
	# Receive a dictionary, each item to control a function in the Pi
	# Write the control dictionary to a file, so that it's accessible to all threads, regardless how they were started
	# Other threads can open this file, extract the dictionary, and obey the control request
	ctrlDict = json.loads(ctrlDictJson)
	with open(CTR_FILE, 'wb+') as ctrlFile:
		pickle.dump(ctrlDict, ctrlFile)
	return 'OK control'

def doLinuxCmd(linuxCmd):
	"""Do a Linux command"""
	
	linuxCmdList = linuxCmd.split(' ')
	linuxResponse = None
	try:
		linuxResponse = subprocess.check_output(linuxCmdList)
		print linuxResponse
	except subprocess.CalledProcessError as e:
		print 'ERROR: ',
		print e
	return linuxResponse


def postLogDataSrvc(logDataStr):
	"""Log data to the USB drive"""

	global dataLogFile

	# Locals
	USB_DIR = MEDIA_DIR + '/%s'
	DATA_LOG_FILE_PATH = MEDIA_DIR + '/%s/lithiumatelog_%s.csv'
	FILE_NAME_BASE = 'lithiumatelog_'
	UNMOUNT_USB_CODE = 'U'
	EJECT_USB_CMD = 'sudo eject /media/pi/%s'
	DEL_DIR_CMD = 'sudo rm -r %s/%s'
	
	responseStr = ''
		
	# Find a USB drive
	usbDriveName = ''
	usbDrivesList = os.listdir(MEDIA_DIR)
	if len(usbDrivesList) > 0:
	
		# There is a USB stick
		usbDriveName = usbDrivesList[0]
	
		# Stop logging
		if logDataStr == '':
			if dataLogFile:
				dataLogFile.close()
				dataLogFile = None
				responseStr = 'Stopped'
		
		# Unmount the USB stick
		elif logDataStr == UNMOUNT_USB_CODE:
			doLinuxCmd(EJECT_USB_CMD % usbDriveName)

		# Log data
		else:
		
			# Start a new file (if required)
			if dataLogFile == None:
				# Next file number
				maxSeqNo = 0
				usbDrivesFileList = os.listdir(USB_DIR % usbDriveName)
				for fileName in usbDrivesFileList:
					fileNameNoExt = fileName.split('.')[0]
					if FILE_NAME_BASE in fileNameNoExt:
						seqNoStr = fileNameNoExt[len(FILE_NAME_BASE):]
						seqNo = 0
						try:
							seqNo = int(seqNoStr)
						except:
							pass
						if seqNo > maxSeqNo:
							maxSeqNo = seqNo
				# Open or create the file
				seqNoStr = str(maxSeqNo + 1)
				data_log_file_path = DATA_LOG_FILE_PATH % (usbDriveName, seqNoStr)
				dataLogFile = open(data_log_file_path, 'w+')
				
			# Log data
			if dataLogFile != None:
				dataLogFile.write(logDataStr + '\n')

	# No USB stick
	else:
		responseStr = 'No USB drive'
		
	return responseStr

def clearGhostDrives():
	"""Delete non-existent USB drives"""
	# When power is removed (no shut-down) and a USB drive is removed, 
	#  then the power is restored, a ghost folder is left in /media/pi/
	# Distinguishing between ghost folders and real ones has proven to be too much of a challenge
	# Instead, this function deletes all the USB folders
	# This is executed when powering up, before the USB drive is mounted
	# Therefore, after this removes all the folders, the system mounts the USB drive that actually exists
	
	# Locals
	DEL_DIR_CMD = 'sudo rm -r %s/%s'
	
	usbDrivesList = os.listdir(MEDIA_DIR)
	if len(usbDrivesList) > 1:
		for usbDriveName in usbDrivesList:
			doLinuxCmd(DEL_DIR_CMD % (MEDIA_DIR, usbDriveName))	

def forceChromiumExitedOK():
	"""Edit Chromium's preference file so it doesn't know if it didn't shut down properly"""

	# Locals
	CHROMIUM_PREFS_PATH = '/home/pi/.config/chromium/Default/Preferences'
	
	chromiumPrefsFile = open(CHROMIUM_PREFS_PATH, 'r')
	chromiumPrefsStr = chromiumPrefsFile.read()
	chromiumPrefsFile.close()
	chromiumPrefsStr = chromiumPrefsStr.replace('"exited_cleanly":false', '"exited_cleanly":true')
	chromiumPrefsStr = chromiumPrefsStr.replace('"exit_type":"Crashed"', '"exit_type":"Normal"')
	chromiumPrefsFile = open(CHROMIUM_PREFS_PATH, 'w')
	chromiumPrefsFile.write(chromiumPrefsStr)
	chromiumPrefsFile.close()
	

def getReboot():
	"""Rebbot the Pi"""
	REBOOT_CMD = 'reboot'
	doLinuxCmd(REBOOT_CMD)
	return 0
	

# MAIN


if __name__ == '__main__':

	print 'Starting Lithiumate data logger'

        f = open("test.txt", "w+")
	# Output log
	if LOG_OUT:
		sys.stdout = open(LOG_FILE_PATH,'w')

	# Validate the install
	if validateInstall(): # If not a bootleg copy
		clearData() # Clear the data dictionary
		clearGhostDrives() # Delete non-existent USB drives
		forceChromiumExitedOK()
		time.sleep(REQ_DLY)
		mainLoop() # Start the main loop to request data, receive it and parse it
