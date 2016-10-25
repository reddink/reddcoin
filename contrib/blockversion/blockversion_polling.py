#!/usr/bin/python
#
# blockversion.py:  Construct a list of blocks and version.
#
#
# Copyright (c) 2016 The Reddcoin developers
# Distributed under the MIT/X11 software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
#

import json
import struct
import re
import base64
import httplib
import sys
import sqlite3
from time import gmtime, strftime, localtime, sleep

ERR_SLEEP = 15
MAX_NONCE = 1000000L

settings = {}

class BitcoinRPC:
	OBJID = 1

	def __init__(self, host, port, username, password):
		authpair = "%s:%s" % (username, password)
		self.authhdr = "Basic %s" % (base64.b64encode(authpair))
		self.conn = httplib.HTTPConnection(host, port, False, 30)
	def rpc(self, method, params=None):
		self.OBJID += 1
		obj = { 'version' : '1.1',
			'method' : method,
			'id' : self.OBJID }
		if params is None:
			obj['params'] = []
		else:
			obj['params'] = params
		self.conn.request('POST', '/', json.dumps(obj),
			{ 'Authorization' : self.authhdr,
			  'Content-type' : 'application/json' })

		resp = self.conn.getresponse()
		if resp is None:
			print "JSON-RPC: no response"
			return None

		body = resp.read()
		resp_obj = json.loads(body)
		if resp_obj is None:
			print "JSON-RPC: cannot JSON-decode body"
			return None
		if 'error' in resp_obj and resp_obj['error'] != None:
			return resp_obj['error']
		if 'result' not in resp_obj:
			print "JSON-RPC: no result in object"
			return None

		return resp_obj['result']

	def getblockcount(self):
		return self.rpc('getblockcount')
	def getblock(self, hash, verbose=True):
		return self.rpc('getblock', [hash, verbose])
	def getblockhash(self, index):
		return self.rpc('getblockhash', [index])

def getblockcount(rpc):
	count = rpc.getblockcount()

	return count

def getblock(rpc, settings, n):
	hash = rpc.getblockhash(n)
	blockdata = rpc.getblock(hash)
	#data = hexdata.decode('hex')

	return blockdata

def get_blocks(settings):
	rpc = BitcoinRPC(settings['host'], settings['port'],
			 settings['rpcuser'], settings['rpcpassword'])

	# conn to db
	conn=sqlite3.connect('./' + settings['db'])
	print "Database created and opened" + repr('./' + settings['db'])

	cur = conn.cursor()

	cur.execute ("create table if not exists blocks(ID INTEGER PRIMARY KEY, BLOCK INTEGER, TIME INTEGER, VERSION INTEGER, DIFFICULTY INTEGER)")
	cur.execute ("CREATE TABLE IF NOT EXISTS blockversion (ID INTEGER PRIMARY KEY, HEIGHT INTEGER, VER1COUNT INTEGER, VER2COUNT INTEGER, VER3COUNT INTEGER, VER4COUNT INTEGER)")
	#conn.commit()

	if (settings['max_height'] == 0):
		max_height = getblockcount(rpc)

	cur.execute ("SELECT * FROM blocks WHERE ID = (SELECT MAX(ID) FROM blocks)")
	data = cur.fetchone()
	#print "The last Id of the inserted row is %d" % data

	if data != None:
		print "The last Id of the inserted row is %d block %d" % (data[0],data[1])
		#print "Next block to insert is %d" % data[1] + 1)
		min_height = data[1] +1
	else:
		print "last row not exist in db. must be new"
		min_height = settings['min_height']
	
	print "MaxHeight = " + repr(max_height)
	print "MinHeight = " + repr(min_height)

	while True:
		if min_height <= max_height:
			print strftime("%Y/%m/%d %H:%M:%S", localtime()) + " Process Blocks " + repr(min_height) + " - " + repr(max_height)
			for height in xrange(min_height, max_height + 1):
				blockdata = getblock(rpc, settings, height)
				blktime = blockdata["time"]
				blkheight = blockdata["height"]
				blkversion = blockdata["version"]
				blkdifficulty = blockdata["difficulty"]

				
				# insert current block
				cur.execute ('INSERT INTO blocks VALUES (?,?,?,?,?)', (None, height, blktime, blkversion,blkdifficulty))
				conn.commit()


				# get the last inserted block(s)
				cur.execute("SELECT BLOCK FROM blocks LEFT OUTER JOIN blockversion ON blocks.BLOCK = blockversion.HEIGHT WHERE blocks.BLOCK > ( SELECT MAX(blockversion.HEIGHT) FROM blockversion )") 
				blockdata = cur.fetchall()

				if len(blockdata) == 0:
					print strftime("%Y/%m/%d %H:%M:%S", localtime()) + " No block details in blockversion"
                                        print strftime("%Y/%m/%d %H:%M:%S", localtime()) + " Calculating block count for block = " + repr(height)

					# get version count
					cur.execute("SELECT version, count(*) FROM blocks WHERE BLOCK <= " + repr(height) + " GROUP BY version ORDER BY version ASC")
					data = cur.fetchall()

					ver1count = 0
					ver2count = 0
					ver3count = 0
					ver4count = 0

					for row in data:
						if row[0] == 1: ver1count = row[1]
						elif row[0] == 2: ver2count = row[1]
						elif row[0] == 3: ver3count = row[1]
						elif row[0] == 4: ver4count = row[1]


					print strftime("%Y/%m/%d %H:%M:%S", localtime()) + " Inserting block count for block = " + repr(height)
					cur.execute('INSERT INTO blockversion VALUES (?,?,?,?,?,?)', (None, height, ver1count, ver2count, ver3count, ver4count))
					conn.commit()

				else:
                                        #print strftime("%Y/%m/%d %H:%M:%S", localtime()) + " Calculating block count for block = " + repr(blockdata)

					for block in blockdata:
						#print strftime("%Y/%m/%d %H:%M:%S", localtime()) + " Calculating block count for block = " + repr(block[0])

						# get version count
						cur.execute("SELECT version, count(*) FROM blocks WHERE BLOCK <= " + repr(block[0]) + " GROUP BY version ORDER BY version ASC")
						data = cur.fetchall()

						ver1count = 0
						ver2count = 0
						ver3count = 0
						ver4count = 0

						for row in data:
							if row[0] == 1: ver1count = row[1]
							elif row[0] == 2: ver2count = row[1]
							elif row[0] == 3: ver3count = row[1]
							elif row[0] == 4: ver4count = row[1]


						#print strftime("%Y/%m/%d %H:%M:%S", localtime()) + " Inserting block count for block = " + repr(block[0])
						cur.execute('INSERT INTO blockversion VALUES (?,?,?,?,?,?)', (None, block[0], ver1count, ver2count, ver3count, ver4count))
						conn.commit()




				if (height % 1000) == 0:
					sys.stdout.write(strftime("%Y/%m/%d %H:%M:%S", localtime()) + " Wrote block " + str(height) + "\n")
			
			min_height = height + 1

		else:
			print strftime("%Y/%m/%d %H:%M:%S", localtime()) + " No New Blocks detected - sleep 30s"
			sleep(30)


		max_height = getblockcount(rpc)

	#close DB
	if conn:
		conn.close()

if __name__ == '__main__':
	if len(sys.argv) != 2:
		print "Usage: blockversion.py CONFIG-FILE"
		sys.exit(1)

	f = open(sys.argv[1])
	for line in f:
		# skip comment lines
		m = re.search('^\s*#', line)
		if m:
			continue

		# parse key=value lines
		m = re.search('^(\w+)\s*=\s*(\S.*)$', line)
		if m is None:
			continue
		settings[m.group(1)] = m.group(2)
	f.close()

	if 'netmagic' not in settings:
		settings['netmagic'] = 'f9beb4d9'
	if 'host' not in settings:
		settings['host'] = '127.0.0.1'
	if 'port' not in settings:
		settings['port'] = 45443
	if 'min_height' not in settings:
		settings['min_height'] = 0
	if 'max_height' not in settings:
		settings['max_height'] = 0 #if zero we will read from blockchain for last block height
	if 'step' not in settings:
		settings['step'] = 1
	if 'db' not in settings:
		settings['db'] = 'blockversion.db'
	if 'rpcuser' not in settings or 'rpcpassword' not in settings:
		print "Missing username and/or password in cfg file"
		sys.exit(1)

	settings['netmagic'] = settings['netmagic'].decode('hex')
	settings['port'] = int(settings['port'])
	settings['min_height'] = int(settings['min_height'])
	settings['max_height'] = int(settings['max_height'])
	settings['step'] = int(settings['step'])

	get_blocks(settings)

