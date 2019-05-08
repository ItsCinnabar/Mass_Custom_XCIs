import aes128
import Title
import Titles
import Hex
from binascii import hexlify as hx, unhexlify as uhx
from struct import pack as pk, unpack as upk
from Fs.File import File
from hashlib import sha256
import Fs.Type
from Fs.Pfs0 import Pfs0
from Fs.BaseFs import BaseFs
import os
import re
import pathlib
import Keys
import Config
import Print
import Nsps
import Fs
from tqdm import tqdm

MEDIA_SIZE = 0x200
indent = 1
tabs = '\t' * indent	


class uHfs0(Pfs0):
	def __init__(self, buffer, path = None, mode = None, cryptoType = -1, cryptoKey = -1, cryptoCounter = -1):
		super(uHfs0, self).__init__(buffer, path, mode, cryptoType, cryptoKey, cryptoCounter)

	def open(self, path = None, mode = 'rb', cryptoType = -1, cryptoKey = -1, cryptoCounter = -1):
		r = super(BaseFs, self).open(path, mode, cryptoType, cryptoKey, cryptoCounter)
		self.rewind()

		self.magic = self.read(0x4);
		if self.magic != b'HFS0':
			raise IOError('Not a valid HFS0 partition ' + str(self.magic))
			

		fileCount = self.readInt32()
		stringTableSize = self.readInt32()
		self.readInt32() # junk data

		self.seek(0x10 + fileCount * 0x40)
		stringTable = self.read(stringTableSize)
		stringEndOffset = stringTableSize
		
		headerSize = 0x10 + 0x40 * fileCount + stringTableSize
		self.files = []
		for i in range(fileCount):
			i = fileCount - i - 1
			self.seek(0x10 + i * 0x40)

			offset = self.readInt64()
			size = self.readInt64()
			nameOffset = self.readInt32() # just the offset
			name = stringTable[nameOffset:stringEndOffset].decode('utf-8').rstrip(' \t\r\n\0')
			stringEndOffset = nameOffset

			self.readInt32() # junk data

			#if name in ['update', 'secure', 'normal']:
			if name == 'update':
				Print.info('Parsing update partition, please wait')		
				f = uHfs0(None)
				#f = factory(name)
			else:
				f = Fs.factory(name)	

			f._path = name
			f.offset = offset
			f.size = size
			self.files.append(self.partition(offset + headerSize, f.size, f))

		self.files.reverse()

	def printInfo(self, indent = 0):
		maxDepth = 3
		tabs = '\t' * indent
		Print.info('\n%sHFS0\n' % (tabs))
		super(Pfs0, self).printInfo(indent)

class nHfs0(Pfs0):
	def __init__(self, buffer, path = None, mode = None, cryptoType = -1, cryptoKey = -1, cryptoCounter = -1):
		super(nHfs0, self).__init__(buffer, path, mode, cryptoType, cryptoKey, cryptoCounter)

	def open(self, path = None, mode = 'rb', cryptoType = -1, cryptoKey = -1, cryptoCounter = -1):
		r = super(BaseFs, self).open(path, mode, cryptoType, cryptoKey, cryptoCounter)
		self.rewind()

		self.magic = self.read(0x4);
		if self.magic != b'HFS0':
			raise IOError('Not a valid HFS0 partition ' + str(self.magic))
			

		fileCount = self.readInt32()
		stringTableSize = self.readInt32()
		self.readInt32() # junk data

		self.seek(0x10 + fileCount * 0x40)
		stringTable = self.read(stringTableSize)
		stringEndOffset = stringTableSize
		
		headerSize = 0x10 + 0x40 * fileCount + stringTableSize
		self.files = []

		for i in range(fileCount):
			i = fileCount - i - 1
			self.seek(0x10 + i * 0x40)

			offset = self.readInt64()
			size = self.readInt64()
			nameOffset = self.readInt32() # just the offset
			name = stringTable[nameOffset:stringEndOffset].decode('utf-8').rstrip(' \t\r\n\0')
			stringEndOffset = nameOffset

			self.readInt32() # junk data

			#if name in ['update', 'secure', 'normal']:
			if name == 'normal':
				f = nHfs0(None)
				#f = factory(name)
			else:
				f = Fs.factory(name)

			f._path = name
			f.offset = offset
			f.size = size
			self.files.append(self.partition(offset + headerSize, f.size, f))

		self.files.reverse()

	def printInfo(self, indent = 0):
		maxDepth = 3
		tabs = '\t' * indent
		Print.info('\n%sHFS0\n' % (tabs))
		super(Pfs0, self).printInfo(indent)		