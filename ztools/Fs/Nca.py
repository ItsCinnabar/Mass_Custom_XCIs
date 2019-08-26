import aes128
import Title
import Titles
import Hex
import math
from binascii import hexlify as hx, unhexlify as uhx
from struct import pack as pk, unpack as upk
from hashlib import sha256
import Fs.Type
import os
import re
import pathlib
import Keys
import Config
import Print
import Nsps
from tqdm import tqdm
import Fs
from Fs import Type
from Fs.File import File
from Fs.File import MemoryFile
from Fs.Rom import Rom
from Fs.Pfs0 import Pfs0
from Fs.BaseFs import BaseFs
from Fs.Ticket import Ticket
from Fs.Nacp import Nacp
import sq_tools
import pykakasi
from Fs.pyNCA3 import NCA3
import io

MEDIA_SIZE = 0x200
RSA_PUBLIC_EXPONENT = 0x10001
FS_HEADER_LENGTH = 0x200
nca_header_fixed_key_modulus = 0xBFBE406CF4A780E9F07D0C99611D772F96BC4B9E58381B03ABB175499F2B4D5834B005A37522BE1A3F0373AC7068D116B904465EB707912F078B26DEF60007B2B451F80D0A5E58ADEBBC9AD649B964EFA782B5CF6D7013B00F85F6A908AA4D676687FA89FF7590181E6B3DE98A68C92604D980CE3F5E92CE01FF063BF2C1A90CCE026F16BC92420A4164CD52B6344DAEC02EDEA4DF27683CC1A060AD43F3FC86C13E6C46F77C299FFAFDF0E3CE64E735F2F656566F6DF1E242B08340A5C3202BCC9AAECAED4D7030A8701C70FD1363290279EAD2A7AF3528321C7BE62F1AAA407E328C2742FE8278EC0DEBE6834B6D8104401A9E9A67F67229FA04F09DE4F403
indent = 1
tabs = '\t' * indent	

from Crypto.Hash import SHA256
from Crypto.Cipher import AES
from Crypto.Util import Counter
from Crypto.PublicKey import RSA 
from Crypto.Signature import PKCS1_v1_5, PKCS1_PSS


class SectionTableEntry:
	def __init__(self, d):
		self.mediaOffset = int.from_bytes(d[0x0:0x4], byteorder='little', signed=False)
		self.mediaEndOffset = int.from_bytes(d[0x4:0x8], byteorder='little', signed=False)
		
		self.offset = self.mediaOffset * MEDIA_SIZE
		self.endOffset = self.mediaEndOffset * MEDIA_SIZE
		
		self.unknown1 = int.from_bytes(d[0x8:0xc], byteorder='little', signed=False)
		self.unknown2 = int.from_bytes(d[0xc:0x10], byteorder='little', signed=False)
		self.sha1 = None
		
	
def GetSectionFilesystem(buffer, cryptoKey):
	fsType = buffer[0x3]
	if fsType == Fs.Type.Fs.PFS0:
		return Fs.Pfs0(buffer, cryptoKey = cryptoKey)
		
	if fsType == Fs.Type.Fs.ROMFS:
		return Fs.Rom(buffer, cryptoKey = cryptoKey)
		
	return BaseFs(buffer, cryptoKey = cryptoKey)
	
class NcaHeader(File):
	def __init__(self, path = None, mode = None, cryptoType = -1, cryptoKey = -1, cryptoCounter = -1):
		self.signature1 = None
		self.signature2 = None
		self.magic = None
		self.isGameCard = None
		self.contentType = None
		self.cryptoType = None
		self.keyIndex = None
		self.size = None
		self.titleId = None
		self.sdkVersion1 = None
		self.sdkVersion2 = None
		self.sdkVersion3 = None
		self.sdkVersion4 = None		
		self.cryptoType2 = None
		self.rightsId = None
		self.titleKeyDec = None
		self.masterKey = None
		self.sectionTables = []
		self.keys = []
		
		super(NcaHeader, self).__init__(path, mode, cryptoType, cryptoKey, cryptoCounter)
		
	def open(self, file = None, mode = 'rb', cryptoType = -1, cryptoKey = -1, cryptoCounter = -1):
		super(NcaHeader, self).open(file, mode, cryptoType, cryptoKey, cryptoCounter)
		self.rewind()
		self.signature1 = self.read(0x100)
		self.signature2 = self.read(0x100)
		self.magic = self.read(0x4)
		self.isGameCard = self.readInt8()
		self.contentType = self.readInt8()

		try:
			self.contentType = Fs.Type.Content(self.contentType)
		except:
			pass

		self.cryptoType = self.readInt8()
		self.keyIndex = self.readInt8()
		self.size = self.readInt64()
		self.titleId = hx(self.read(8)[::-1]).decode('utf-8').upper()
		
		self.readInt32() # padding
		

		self.sdkVersion1 = self.readInt8()
		self.sdkVersion2 = self.readInt8()
		self.sdkVersion3 = self.readInt8()
		self.sdkVersion4 = self.readInt8()		
		self.cryptoType2 = self.readInt8()
		
		self.read(0xF) # padding
		
		self.rightsId = hx(self.read(0x10))
		
		if self.magic not in [b'NCA3', b'NCA2']:
			raise Exception('Failed to decrypt NCA header: ' + str(self.magic))
		
		self.sectionHashes = []
		
		for i in range(4):
			self.sectionTables.append(SectionTableEntry(self.read(0x10)))
			
		for i in range(4):
			self.sectionHashes.append(self.sectionTables[i])

		self.masterKey = (self.cryptoType if self.cryptoType > self.cryptoType2 else self.cryptoType2)-1

		if self.masterKey < 0:
			self.masterKey = 0
		
		
		self.encKeyBlock = self.getKeyBlock()
		#for i in range(4):
		#	offset = i * 0x10
		#	key = encKeyBlock[offset:offset+0x10]
		#	Print.info('enc %d: %s' % (i, hx(key)))

		if Keys.keyAreaKey(self.masterKey, self.keyIndex):
			crypto = aes128.AESECB(Keys.keyAreaKey(self.masterKey, self.keyIndex))
			self.keyBlock = crypto.decrypt(self.encKeyBlock)
			self.keys = []
			for i in range(4):
				offset = i * 0x10
				key = self.keyBlock[offset:offset+0x10]
				#Print.info('dec %d: %s' % (i, hx(key)))
				self.keys.append(key)
		else:
			self.keys = [None, None, None, None, None, None, None]
		

		if self.hasTitleRights():
			if self.titleId.upper() in Titles.keys() and Titles.get(self.titleId.upper()).key:
				self.titleKeyDec = Keys.decryptTitleKey(uhx(Titles.get(self.titleId.upper()).key), self.masterKey)
			else:
				pass
				#Print.info('could not find title key!')
		else:
			self.titleKeyDec = self.key()

	def key(self):
		return self.keys[2]
		return self.keys[self.cryptoType]

	def hasTitleRights(self):
		return self.rightsId != (b'0' * 32)

	def getKeyBlock(self):
		self.seek(0x300)
		return self.read(0x40)

	def getKB1L(self):
		self.seek(0x300)
		return self.read(0x10)		

	def setKeyBlock(self, value):
		if len(value) != 0x40:
			raise IOError('invalid keyblock size')
		self.seek(0x300)
		return self.write(value)

	def getCryptoType(self):
		self.seek(0x206)
		return self.readInt8()

	def setCryptoType(self, value):
		self.seek(0x206)
		self.writeInt8(value)
		
	def setgamecard(self, value):
		self.seek(0x204)
		self.writeInt8(value)
		
	def getgamecard(self):
		self.seek(0x204)
		return self.readInt8()

	def getCryptoType2(self):
		self.seek(0x220)
		return self.readInt8()

	def setCryptoType2(self, value):
		self.seek(0x220)
		self.writeInt8(value)

	def getRightsId(self):
		self.seek(0x230)
		return self.readInt128('big')

	def setRightsId(self, value):
		self.seek(0x230)
		self.writeInt128(value, 'big')
			
	def get_hblock_hash(self):
		self.seek(0x280)
		return self.read(0x20)
		
	def set_hblock_hash(self, value):
		self.seek(0x280)
		return self.write(value)		

	def calculate_hblock_hash(self):
		indent = 2
		tabs = '\t' * indent
		self.seek(0x400)
		hblock = self.read(0x200)	 
		sha=sha256(hblock).hexdigest()		
		sha_hash= bytes.fromhex(sha)
		#Print.info(tabs + 'calculated header block hash: ' + str(hx(sha_hash)))
		return sha_hash 
		
	def get_hblock_version(self):
		self.seek(0x400)
		return self.read(0x02)	
		
	def get_hblock_filesystem(self):
		self.seek(0x403)
		return self.read(0x01)	

	def get_hblock_hash_type(self):
		self.seek(0x404)
		return self.read(0x01)	
		
	def get_hblock_crypto_type(self):
		self.seek(0x405)
		return self.read(0x01)	
		
	def get_htable_hash(self):
		self.seek(0x408)
		return self.read(0x20)	

	def set_htable_hash(self, value):
		self.seek(0x408)
		return self.write(value)		
	
	def get_hblock_block_size(self):
		self.seek(0x428)
		return self.readInt32()

	def get_hblock_uk1(self):
		self.seek(0x42C)
		return self.read(0x04)			

	def get_htable_offset(self):
		self.seek(0x430)
		return self.readInt64()	
		
	def get_htable_size(self):
		self.seek(0x438)
		return self.readInt64()				
	
	def get_pfs0_offset(self):
		self.seek(0x440)
		return self.readInt64()			
		
	def get_pfs0_size(self):
		self.seek(0x448)
		return self.readInt64()			


class Nca(File):
	def __init__(self, path = None, mode = 'rb', cryptoType = -1, cryptoKey = -1, cryptoCounter = -1):
		self.header = None
		self.sectionFilesystems = []
		super(Nca, self).__init__(path, mode, cryptoType, cryptoKey, cryptoCounter)
			
	def __iter__(self):
		return self.sectionFilesystems.__iter__()
		
	def __getitem__(self, key):
		return self.sectionFilesystems[key]

	def open(self, file = None, mode = 'rb', cryptoType = -1, cryptoKey = -1, cryptoCounter = -1):

		super(Nca, self).open(file, mode, cryptoType, cryptoKey, cryptoCounter)

		self.header = NcaHeader()
		self.partition(0x0, 0xC00, self.header, Fs.Type.Crypto.XTS, uhx(Keys.get('header_key')))
		#Print.info('partition complete, seeking')
		
		self.header.seek(0x400)
		#Print.info('reading')
		#Hex.dump(self.header.read(0x200))
		#exit()

		for i in range(4):
			fs = GetSectionFilesystem(self.header.read(0x200), cryptoKey = self.header.titleKeyDec)
			#Print.info('fs type = ' + hex(fs.fsType))
			#Print.info('fs crypto = ' + hex(fs.cryptoType))
			#Print.info('st end offset = ' + str(self.header.sectionTables[i].endOffset - self.header.sectionTables[i].offset))
			#Print.info('fs offset = ' + hex(self.header.sectionTables[i].offset))
			#Print.info('fs section start = ' + hex(fs.sectionStart))
			#Print.info('titleKey = ' + str(hx(self.header.titleKeyDec)))
			try:
				self.partition(self.header.sectionTables[i].offset + fs.sectionStart, self.header.sectionTables[i].endOffset - self.header.sectionTables[i].offset, fs, cryptoKey = self.header.titleKeyDec)
			except BaseException as e:
				pass
				#Print.info(e)
				#raise

			if fs.fsType:
				self.sectionFilesystems.append(fs)
		
		
		self.titleKeyDec = None
		self.masterKey = None

	def get_hblock(self):		
		version = self.header.get_hblock_version()
		Print.info('version: ' + str(int.from_bytes(version, byteorder='little')))
		filesystem = self.header.get_hblock_filesystem()
		Print.info('filesystem: ' + str(int.from_bytes(filesystem, byteorder='little')))
		hash_type = self.header.get_hblock_hash_type()
		Print.info('hash type: ' + str(int.from_bytes(hash_type, byteorder='little')))
		crypto_type = self.header.get_hblock_crypto_type()
		Print.info('crypto type: ' + str(int.from_bytes(crypto_type, byteorder='little')))
		hash_from_htable = self.header.get_htable_hash()
		Print.info('hash from hash table: ' + str(hx(hash_from_htable)))
		block_size = self.header.get_hblock_block_size()
		Print.info('block size in bytes: ' + str(hx(block_size.to_bytes(8, byteorder='big'))))
		v_unkn1 = self.header.get_hblock_uk1()
		htable_offset = self.header.get_htable_offset()
		Print.info('hash table offset: ' +  str(hx(htable_offset.to_bytes(8, byteorder='big'))))
		htable_size = self.header.get_htable_size()
		Print.info('Size of hash-table: ' +  str(hx(htable_size.to_bytes(8, byteorder='big'))))			
		pfs0_offset = self.header.get_pfs0_offset()
		Print.info('Pfs0 offset: ' +  str(hx(pfs0_offset.to_bytes(8, byteorder='big'))))	
		pfs0_size = self.header.get_pfs0_size()
		Print.info('Pfs0 size: ' +  str(hx(pfs0_size.to_bytes(8, byteorder='big'))))	
			
		
	def get_pfs0_hash_data(self):	
		block_size = self.header.get_hblock_block_size()
		#Print.info('block size in bytes: ' + str(hx(block_size.to_bytes(8, byteorder='big'))))
		pfs0_size = self.header.get_pfs0_size()
		#Print.info('Pfs0 size: ' +  str(hx(pfs0_size.to_bytes(8, byteorder='big'))))
		multiplier=pfs0_size/block_size
		multiplier=math.ceil(multiplier)
		#Print.info('Multiplier: ' +  str(multiplier))
		return pfs0_size,block_size,multiplier
		
	def pfs0_MULT(self):	
		block_size = self.header.get_hblock_block_size()
		#Print.info('block size in bytes: ' + str(hx(block_size.to_bytes(8, byteorder='big'))))
		pfs0_size = self.header.get_pfs0_size()
		#Print.info('Pfs0 size: ' +  str(hx(pfs0_size.to_bytes(8, byteorder='big'))))
		multiplier=pfs0_size/block_size
		multiplier=math.ceil(multiplier)
		#Print.info('Multiplier: ' +  str(multiplier))
		return multiplier		
	
	def get_pfs0_hash(self, file = None, mode = 'rb', cryptoType = -1, cryptoKey = -1, cryptoCounter = -1):		
		mult=self.pfs0_MULT()
		for f in self:
			cryptoType=f.get_cryptoType()
			cryptoKey=f.get_cryptoKey()	
			cryptoCounter=f.get_cryptoCounter()
		super(Nca, self).open(file, mode, cryptoType, cryptoKey, cryptoCounter)
		self.seek(0xC00+self.header.get_htable_offset())
		hash_from_pfs0=self.read(0x20*mult)
		return hash_from_pfs0
		
	def extract(self,ofolder,buffer):		
		ncaname =  str(self._path)[:-4]+'_nca'
		ncafolder = os.path.join(ofolder,ncaname)
		if not os.path.exists(ncafolder):
			os.makedirs(ncafolder)
		nca3 = NCA3(open(str(self._path), 'rb'))			
		nca3.extract_conts(ncafolder, disp=True)
		
	def calc_htable_hash(self):		
		indent = 2
		tabs = '\t' * indent
		htable = self.get_pfs0_hash()
		sha=sha256(htable).hexdigest()		
		sha_hash= bytes.fromhex(sha)
		#Print.info(tabs + 'calculated table hash: ' + str(hx(sha_hash)))
		return sha_hash		

	def calc_pfs0_hash(self, file = None, mode = 'rb'):	
		mult=self.pfs0_MULT()
		indent = 2
		tabs = '\t' * indent
		for f in self:
			cryptoType2=f.get_cryptoType()
			cryptoKey2=f.get_cryptoKey()	
			cryptoCounter2=f.get_cryptoCounter()
		super(Nca, self).open(file, mode, cryptoType2, cryptoKey2, cryptoCounter2)
		pfs0_offset = self.header.get_pfs0_offset()
		pfs0_size = self.header.get_pfs0_size()
		block_size = self.header.get_hblock_block_size()
		self.seek(0xC00+self.header.get_htable_offset()+pfs0_offset)
		if mult>1:
			pfs0=self.read(block_size)
		else:
			pfs0=self.read(pfs0_size)
		sha=sha256(pfs0).hexdigest()
		#Print.info('caculated hash from pfs0: ' + sha)	
		sha_signature = bytes.fromhex(sha)
		#Print.info(tabs + 'calculated hash from pfs0: ' + str(hx(sha_signature)))
		return sha_signature
		
	def set_pfs0_hash(self,value):
		file = None	
		mode = 'r+b'
		for f in self:
			cryptoType2=f.get_cryptoType()
			cryptoKey2=f.get_cryptoKey()	
			cryptoCounter2=f.get_cryptoCounter()
		super(Nca, self).open(file, mode, cryptoType2, cryptoKey2, cryptoCounter2)
		self.seek(0xC00+self.header.get_htable_offset())
		self.write(value)		
		
	def test(self,titleKeyDec, file = None, mode = 'rb'):	
		indent = 1
		tabs = '\t' * indent
		self.header = NcaHeader()
		self.partition(0x0, 0xC00, self.header, Fs.Type.Crypto.XTS, uhx(Keys.get('header_key')))
		Print.info('partition complete, seeking')
		self.rewind()
		self.header.seek(0x400)
		Print.info('reading')
		Hex.dump(self.header.read(0x200))
		#exit()

		for i in range(4):		
			fs = GetSectionFilesystem(self.header.read(0x200), cryptoKey = titleKeyDec)
			Print.info('fs type = ' + hex(fs.fsType))
			Print.info('fs crypto = ' + hex(fs.cryptoType))
			Print.info('st end offset = ' + str(self.header.sectionTables[i].endOffset - self.header.sectionTables[i].offset))
			Print.info('fs offset = ' + hex(self.header.sectionTables[i].offset))
			Print.info('fs section start = ' + hex(fs.sectionStart))
			Print.info('titleKey = ' + str(hx(titleKeyDec)))		
			try:
				self.partition(self.header.sectionTables[i].offset + fs.sectionStart, self.header.sectionTables[i].endOffset - self.header.sectionTables[i].offset, fs, cryptoKey = titleKeyDec)
			except BaseException as e:
				pass
				#Print.info(e)
				#raise

			if fs.fsType:
				self.sectionFilesystems.append(fs)			
		for f in self:
			print(type(f))
			cryptoType=f.get_cryptoType()
			cryptoKey=f.get_cryptoKey()				
			cryptoCounter=f.get_cryptoCounter()			
			super(Nca, self).open(file, mode, cryptoType, cryptoKey, cryptoCounter)		
			for g in f:		
				print(type(g))				
				if type(g) == File:				
					print(str(g._path))
					print(g.read(0x10))
					
	def pr_noenc_check(self, file = None, mode = 'rb'):	
		indent = 1
		tabs = '\t' * indent
		check = False
		for f in self:
			#print(type(f))
			cryptoType=f.get_cryptoType()
			cryptoKey=f.get_cryptoKey()				
			cryptoCounter=f.get_cryptoCounter()			
			super(Nca, self).open(file, mode, cryptoType, cryptoKey, cryptoCounter)		
			for g in f:					
				if type(g) == File:		
					if (str(g._path)) == 'main.npdm':
						check = True
						break
		return check	
		
	def pr_noenc_check_dlc(self, file = None, mode = 'rb'):	
		crypto1=self.header.getCryptoType()	
		crypto2=self.header.getCryptoType2()		
		if crypto1 == 2:
			if crypto1 > crypto2:								
				masterKeyRev=crypto1
			else:			
				masterKeyRev=crypto2
		else:			
			masterKeyRev=crypto2	
		decKey = Keys.decryptTitleKey(self.header.titleKeyDec, Keys.getMasterKeyIndex(masterKeyRev))
		for f in self.sectionFilesystems:
			#print(f.fsType);print(f.cryptoType)
			if f.fsType == Type.Fs.ROMFS and f.cryptoType == Type.Crypto.CTR:	
				ncaHeader = NcaHeader()
				self.header.rewind()
				ncaHeader = self.header.read(0x400)
				#Hex.dump(ncaHeader)
				pfs0=f
				#Hex.dump(pfs0.read())
				sectionHeaderBlock = f.buffer

				levelOffset = int.from_bytes(sectionHeaderBlock[0x18:0x20], byteorder='little', signed=False)
				levelSize = int.from_bytes(sectionHeaderBlock[0x20:0x28], byteorder='little', signed=False)

				pfs0Header = pfs0.read(levelSize)
				if sectionHeaderBlock[8:12] == b'IVFC':	
					data = pfs0Header;
					#Hex.dump(pfs0Header)
					if hx(sectionHeaderBlock[0xc8:0xc8+0x20]).decode('utf-8') == str(sha256(data).hexdigest()):
						return True
					else:
						return False
				else:
					data = pfs0Header;
					#Hex.dump(pfs0Header)				
					magic = pfs0Header[0:4]
					if magic != b'PFS0':
						return False
					else:	
						return True		
	
	def get_req_system(self, file = None, mode = 'rb'):	
		indent = 1
		tabs = '\t' * indent
		for f in self:
			cryptoType=f.get_cryptoType()
			cryptoKey=f.get_cryptoKey()	
			cryptoCounter=f.get_cryptoCounter()		
		pfs0_offset=0xC00+self.header.get_htable_offset()+self.header.get_pfs0_offset()
		super(Nca, self).open(file, mode, cryptoType, cryptoKey, cryptoCounter)
		self.seek(pfs0_offset+0x8)
		pfs0_table_size=self.readInt32()
		cmt_offset=pfs0_offset+0x28+pfs0_table_size
		self.seek(cmt_offset+0x28)		
		min_sversion=self.readInt32()
		#Print.info(tabs + 'RequiredSystemVersion = ' + str(min_sversion))
		return min_sversion		

	def write_req_system(self, verNumber):
		indent = 1
		tabs = '\t' * indent
		file = None
		mode = 'r+b'	
		for f in self:
			cryptoType=f.get_cryptoType()
			cryptoKey=f.get_cryptoKey()	
			cryptoCounter=f.get_cryptoCounter()
		pfs0_offset=0xC00+self.header.get_htable_offset()+self.header.get_pfs0_offset()
		super(Nca, self).open(file, mode, cryptoType, cryptoKey, cryptoCounter)
		self.seek(pfs0_offset+0x8)
		pfs0_table_size=self.readInt32()
		cmt_offset=pfs0_offset+0x28+pfs0_table_size
		self.seek(cmt_offset+0x28)	
		min_sversion=self.readInt32()
		#Print.info('Original RequiredSystemVersion = ' + str(min_sversion))
		self.seek(cmt_offset+0x28)	
		self.writeInt32(verNumber)
		self.seek(cmt_offset+0x28)	
		min_sversion=self.readInt32()
		#Print.info(tabs + 'New RequiredSystemVersion = ' + str(min_sversion))
		return min_sversion

	def write_version(self, verNumber):
		indent = 1
		tabs = '\t' * indent
		file = None
		mode = 'r+b'	
		for f in self:
			cryptoType=f.get_cryptoType()
			cryptoKey=f.get_cryptoKey()	
			cryptoCounter=f.get_cryptoCounter()
		pfs0_offset=0xC00+self.header.get_htable_offset()+self.header.get_pfs0_offset()
		super(Nca, self).open(file, mode, cryptoType, cryptoKey, cryptoCounter)
		self.seek(pfs0_offset+0x8)
		pfs0_table_size=self.readInt32()
		cmt_offset=pfs0_offset+0x28+pfs0_table_size
		self.seek(cmt_offset)
		titleid=self.readInt64()
		tnumber = verNumber.to_bytes(0x04, byteorder='little')
		titleversion = self.write(tnumber)
		self.seek(cmt_offset)
		titleid=self.readInt64()
		titleversion = self.read(0x4)
		Print.info('version = ' + str(int.from_bytes(titleversion, byteorder='little')))
		return titleversion			
		
	def removeTitleRightsnca(self, masterKeyRev, titleKeyDec):
		Print.info('titleKeyDec =\t' + str(hx(titleKeyDec)))
		Print.info('masterKeyRev =\t' + hex(masterKeyRev))
		Print.info('writing masterKeyRev for %s, %d' % (str(self._path),  masterKeyRev))
		crypto = aes128.AESECB(Keys.keyAreaKey(Keys.getMasterKeyIndex(masterKeyRev), self.header.keyIndex))
		encKeyBlock = crypto.encrypt(titleKeyDec * 4)
		self.header.setRightsId(0)
		self.header.setKeyBlock(encKeyBlock)
		Hex.dump(encKeyBlock)		
		
	def printtitleId(self, indent = 0):	
		Print.info(str(self.header.titleId))
		
	def print_nca_type(self, indent = 0):	
		Print.info(str(self.header.contentType))
			
	def cardstate(self, indent = 0):	
		Print.info(hex(self.header.isGameCard))
		
	def read_pfs0_header(self, file = None, mode = 'rb'):
		for f in self:
			cryptoType=f.get_cryptoType()
			cryptoKey=f.get_cryptoKey()	
			cryptoCounter=f.get_cryptoCounter()		
		pfs0_offset=0xC00+self.header.get_htable_offset()+self.header.get_pfs0_offset()
		super(Nca, self).open(file, mode, cryptoType, cryptoKey, cryptoCounter)
		self.seek(pfs0_offset)
		pfs0_magic = self.read(4)
		pfs0_nfiles=self.readInt32()
		pfs0_table_size=self.readInt32()
		pfs0_reserved=self.read(0x4)
		Print.info('PFS0 Magic = ' + str(pfs0_magic))
		Print.info('PFS0 number of files = ' + str(pfs0_nfiles))
		Print.info('PFS0 string table size = ' + str(hx(pfs0_table_size.to_bytes(4, byteorder='big'))))
		for i in range(pfs0_nfiles):
			Print.info('........................')							
			Print.info('PFS0 Content number ' + str(i+1))
			Print.info('........................')
			f_offset = self.readInt64()
			Print.info('offset = ' + str(hx(f_offset.to_bytes(8, byteorder='big'))))
			f_size = self.readInt32()
			Print.info('Size =\t' +  str(hx(pfs0_table_size.to_bytes(4, byteorder='big'))))
			filename_offset = self.readInt32()
			Print.info('offset of filename = ' + str(hx(f_offset.to_bytes(8, byteorder='big'))))
			f_reserved= self.read(0x4)

	def read_cnmt(self, file = None, mode = 'rb'):
		feed=''
		for f in self:
			cryptoType=f.get_cryptoType()
			cryptoKey=f.get_cryptoKey()	
			cryptoCounter=f.get_cryptoCounter()
		pfs0_offset=0xC00+self.header.get_htable_offset()+self.header.get_pfs0_offset()
		pfs0_size = self.header.get_pfs0_size()		
		super(Nca, self).open(file, mode, cryptoType, cryptoKey, cryptoCounter)
		self.seek(pfs0_offset+0x8)
		pfs0_table_size=self.readInt32()
		cmt_offset=pfs0_offset+0x28+pfs0_table_size
		self.seek(cmt_offset)
		titleid=self.readInt64()
		titleversion = self.read(0x4)
		type_n = self.read(0x1)		
		self.seek(cmt_offset+0xE)
		offset=self.readInt16()
		content_entries=self.readInt16()
		meta_entries=self.readInt16()
		self.seek(cmt_offset+0x20)
		original_ID=self.readInt64()
		self.seek(cmt_offset+0x28)					
		min_sversion=self.readInt32()
		length_of_emeta=self.readInt32()	
		basename=str(os.path.basename(os.path.abspath(self._path)))
		message='...........................................';print(message);feed+=message+'\n'	
		message='Reading: ' + str(basename);print(message);feed+=message+'\n'							
		message='...........................................';print(message);feed+=message+'\n'						
		message='Titleid = ' + (str(hx(titleid.to_bytes(8, byteorder='big')))[2:-1]).upper();print(message);feed+=message+'\n'							
		message='Version = ' + str(int.from_bytes(titleversion, byteorder='little'));print(message);feed+=message+'\n'
		message='Table offset = '+ str(hx((offset+0x20).to_bytes(2, byteorder='big')));print(message);feed+=message+'\n'
		message='Number of content = '+ str(content_entries);print(message);feed+=message+'\n'
		message='Number of meta entries = '+ str(meta_entries);print(message);feed+=message+'\n'
		message='Application id\Patch id = ' + (str(hx(original_ID.to_bytes(8, byteorder='big')))[2:-1]).upper();print(message);feed+=message+'\n'	
		message='RequiredVersion = ' + str(min_sversion);print(message);feed+=message+'\n'	
		message='Length of exmeta = ' + str(length_of_emeta);print(message);feed+=message+'\n'		
		self.seek(cmt_offset+offset+0x20)
		for i in range(content_entries):
			message='........................';print(message);feed+=message+'\n'		
			message='Content number ' + str(i+1);print(message);feed+=message+'\n'																
			message='........................';print(message);feed+=message+'\n'
			vhash = self.read(0x20)
			message='Hash =\t' + str(hx(vhash));print(message);feed+=message+'\n'									
			NcaId = self.read(0x10)
			message='NcaId =\t' + str(hx(NcaId));print(message);feed+=message+'\n'											
			size = self.read(0x6)
			message='Size =\t' + str(int.from_bytes(size, byteorder='little', signed=True));print(message);feed+=message+'\n'								
			ncatype = self.read(0x1)
			message='Ncatype = ' + str(int.from_bytes(ncatype, byteorder='little', signed=True));print(message);feed+=message+'\n'								
			unknown = self.read(0x1)	
			
		self.seek(pfs0_offset+pfs0_size-0x20)			
		digest = self.read(0x20)
		message='\ndigest= '+str(hx(digest))+'\n';print(message);feed+=message+'\n'									
		self.seek(cmt_offset+offset+0x20+content_entries*0x38)			
		if length_of_emeta>0:
			message='----------------';print(message);feed+=message+'\n'
			message='Extended meta';print(message);feed+=message+'\n'								
			message='----------------';print(message);feed+=message+'\n'			
			num_prev_cnmt=self.read(0x4)
			num_prev_delta=self.read(0x4)
			num_delta_info=self.read(0x4)
			num_delta_application =self.read(0x4)	
			num_previous_content=self.read(0x4)		
			num_delta_content=self.read(0x4)	
			self.read(0x4)	
			message='Number of previous cnmt entries = ' + str(int.from_bytes(num_prev_cnmt, byteorder='little'));print(message);feed+=message+'\n'								
			message='Number of previous delta entries = ' + str(int.from_bytes(num_prev_delta, byteorder='little'));print(message);feed+=message+'\n'									
			message='Number of delta info entries = ' + str(int.from_bytes(num_delta_info, byteorder='little'));print(message);feed+=message+'\n'									
			message='Number of previous content entries = ' + str(int.from_bytes(num_previous_content, byteorder='little'));print(message);feed+=message+'\n'	
			message='Number of delta content entries = ' + str(int.from_bytes(num_delta_content, byteorder='little'));print(message);feed+=message+'\n'					
			for i in range(int.from_bytes(num_prev_cnmt, byteorder='little')):
				message='...........................................';print(message);feed+=message+'\n'									
				message='Previous cnmt records: '+ str(i+1);print(message);feed+=message+'\n'		
				message='...........................................';print(message);feed+=message+'\n'				
				titleid=self.readInt64()	
				titleversion = self.read(0x4)	
				type_n = self.read(0x1)					
				unknown1=self.read(0x3)
				vhash = self.read(0x20)
				unknown2=self.read(0x2)
				unknown3=self.read(0x2)
				unknown4=self.read(0x4)				
				message='Titleid = ' + str(hx(titleid.to_bytes(8, byteorder='big')));print(message);feed+=message+'\n'
				message='Version = ' + str(int.from_bytes(titleversion, byteorder='little'));print(message);feed+=message+'\n'	
				message='Type number = ' + str(hx(type_n));print(message);feed+=message+'\n'	
				message='Hash =\t' + str(hx(vhash));print(message);feed+=message+'\n'	
				message='Content nca number = ' + str(int.from_bytes(unknown2, byteorder='little'));print(message);feed+=message+'\n'	
			for i in range(int.from_bytes(num_prev_delta, byteorder='little')):
				message='...........................................';print(message);feed+=message+'\n'	
				message='Previous delta records: '+ str(i+1);print(message);feed+=message+'\n'										
				message='...........................................';print(message);feed+=message+'\n'						
				oldtitleid=self.readInt64()	
				newtitleid=self.readInt64()					
				oldtitleversion = self.read(0x4)	
				newtitleversion = self.read(0x4)	
				size = self.read(0x8)
				unknown1=self.read(0x8)				
				message='Old titleid = ' + str(hx(oldtitleid.to_bytes(8, byteorder='big')));print(message);feed+=message+'\n'	
				message='New titleid = ' + str(hx(newtitleid.to_bytes(8, byteorder='big')));print(message);feed+=message+'\n'	
				message='Old version = ' + str(int.from_bytes(oldtitleversion, byteorder='little'));print(message);feed+=message+'\n'	
				message='New version = ' + str(int.from_bytes(newtitleversion, byteorder='little'));print(message);feed+=message+'\n'	
				message='Size = ' + str(int.from_bytes(size, byteorder='little', signed=True));print(message);feed+=message+'\n'					
				#Print.info('unknown1 = ' + str(int.from_bytes(unknown1, byteorder='little')))			
			for i in range(int.from_bytes(num_delta_info, byteorder='little')):
				message='...........................................';print(message);feed+=message+'\n'	
				message='Delta info: '+ str(i+1);print(message);feed+=message+'\n'	
				message='...........................................';print(message);feed+=message+'\n'					
				oldtitleid=self.readInt64()	
				newtitleid=self.readInt64()					
				oldtitleversion = self.read(0x4)	
				newtitleversion = self.read(0x4)	
				index1=self.readInt64()	
				index2=self.readInt64()				
				message='Old titleid = ' + str(hx(oldtitleid.to_bytes(8, byteorder='big')));print(message);feed+=message+'\n'	
				message='New titleid = ' + str(hx(newtitleid.to_bytes(8, byteorder='big')));print(message);feed+=message+'\n'	
				message='Old version = ' + str(int.from_bytes(oldtitleversion, byteorder='little'));print(message);feed+=message+'\n'	
				message='New version = ' + str(int.from_bytes(newtitleversion, byteorder='little'));print(message);feed+=message+'\n'	
				message='Index1 = ' + str(hx(index1.to_bytes(8, byteorder='big')));print(message);feed+=message+'\n'
				message='Index2 = ' + str(hx(index2.to_bytes(8, byteorder='big')));print(message);feed+=message+'\n'						
				#Print.info('unknown1 = ' + str(int.from_bytes(unknown1, byteorder='little')))
			for i in range(int.from_bytes(num_delta_application, byteorder='little')):
				message='...........................................';print(message);feed+=message+'\n'	
				message='Delta application info: '+ str(i+1);print(message);feed+=message+'\n'	
				message='...........................................';print(message);feed+=message+'\n'						
				OldNcaId = self.read(0x10)
				NewNcaId = self.read(0x10)		
				old_size = self.read(0x6)				
				up2bytes = self.read(0x2)
				low4bytes = self.read(0x4)
				unknown1 = self.read(0x2)
				ncatype = self.read(0x1)	
				installable = self.read(0x1)
				unknown2 = self.read(0x4)				
				message='OldNcaId = ' + str(hx(OldNcaId));print(message);feed+=message+'\n'	
				message='NewNcaId = ' + str(hx(NewNcaId));print(message);feed+=message+'\n'	
				message='Old size = ' +  str(int.from_bytes(old_size, byteorder='little', signed=True));print(message);feed+=message+'\n'	
				message='Unknown1 = ' + str(int.from_bytes(unknown1, byteorder='little'));print(message);feed+=message+'\n'	
				message='Ncatype =  ' + str(int.from_bytes(ncatype, byteorder='little', signed=True));print(message);feed+=message+'\n'	
				message='Installable = ' + str(int.from_bytes(installable, byteorder='little'));print(message);feed+=message+'\n'	
				message='Upper 2 bytes of the new size=' + str(hx(up2bytes));print(message);feed+=message+'\n'	
				message='Lower 4 bytes of the new size=' + str(hx(low4bytes));print(message);feed+=message+'\n'
				#Print.info('unknown2 =\t' + str(int.from_bytes(unknown2, byteorder='little')))			

			for i in range(int.from_bytes(num_previous_content, byteorder='little')):
				message='...........................................';print(message);feed+=message+'\n'	
				message='Previous content records: '+ str(i+1);print(message);feed+=message+'\n'	
				message='...........................................';print(message);feed+=message+'\n'				
				NcaId = self.read(0x10)		
				size = self.read(0x6)				
				ncatype = self.read(0x1)	
				unknown1 = self.read(0x1)				
				message='NcaId = '+ str(hx(NcaId));print(message);feed+=message+'\n'	
				message='Size = '+ str(int.from_bytes(size, byteorder='little', signed=True));print(message);feed+=message+'\n'	
				message='Ncatype = '+ str(int.from_bytes(ncatype, byteorder='little', signed=True));print(message);feed+=message+'\n'		
				#Print.info('unknown1 = '+ str(int.from_bytes(unknown1, byteorder='little')))	
				
			for i in range(int.from_bytes(num_delta_content, byteorder='little')):
				message='...........................................';print(message);feed+=message+'\n'	
				message='Delta content entry ' + str(i+1);print(message);feed+=message+'\n'	
				message='...........................................';print(message);feed+=message+'\n'		
				vhash = self.read(0x20)
				message='Hash =\t' + str(hx(vhash));print(message);feed+=message+'\n'										
				NcaId = self.read(0x10)
				message='NcaId =\t' + str(hx(NcaId));print(message);feed+=message+'\n'										
				size = self.read(0x6)
				message='Size =\t' + str(int.from_bytes(size, byteorder='little', signed=True));print(message);feed+=message+'\n'									
				ncatype = self.read(0x1)
				message='Ncatype = ' + str(int.from_bytes(ncatype, byteorder='little', signed=True));print(message);feed+=message+'\n'											
				unknown = self.read(0x1)		
		return feed

	def xml_gen(self,ofolder,nsha):
		file = None
		mode = 'rb'
		crypto1=self.header.getCryptoType()
		crypto2=self.header.getCryptoType2()			
		if crypto2>crypto1:
			keygeneration=crypto2
		if crypto2<=crypto1:	
			keygeneration=crypto1			
		for f in self:
			cryptoType=f.get_cryptoType()
			cryptoKey=f.get_cryptoKey()	
			cryptoCounter=f.get_cryptoCounter()
		pfs0_offset=0xC00+self.header.get_htable_offset()+self.header.get_pfs0_offset()
		pfs0_size = self.header.get_pfs0_size()		
		super(Nca, self).open(file, mode, cryptoType, cryptoKey, cryptoCounter)
		self.seek(pfs0_offset+0x8)
		pfs0_table_size=self.readInt32()
		cmt_offset=pfs0_offset+0x28+pfs0_table_size
		self.seek(cmt_offset)
		titleid=self.readInt64()
		titleversion = self.read(0x4)
		type_n = self.read(0x1)		
		self.seek(cmt_offset+0xE)
		offset=self.readInt16()
		content_entries=self.readInt16()
		meta_entries=self.readInt16()
		self.seek(cmt_offset+0x18)		
		RDSV=self.readInt64()		
		self.seek(cmt_offset+0x20)
		original_ID=self.readInt64()
		self.seek(cmt_offset+0x28)					
		min_sversion=self.readInt32()
		length_of_emeta=self.readInt32()		
		self.seek(cmt_offset+offset+0x20)
		
		if str(hx(type_n)) == "b'1'":
			type='SystemProgram'		
		if str(hx(type_n)) == "b'2'":
			type='SystemData'
		if str(hx(type_n)) == "b'3'":
			type='SystemUpdate'
		if str(hx(type_n)) == "b'4'":
			type='BootImagePackage'		
		if str(hx(type_n)) == "b'5'":
			type='BootImagePackageSafe'		
		if str(hx(type_n)) == "b'80'":
			type='Application'			
		if str(hx(type_n)) == "b'81'":
			type='Patch'
		if str(hx(type_n)) == "b'82'":
			type='AddOnContent'
		if str(hx(type_n)) == "b'83'":
			type='Delta'

		titleid=str(hx(titleid.to_bytes(8, byteorder='big')))	
		titleid='0x'+titleid[2:-1]
		version = str(int.from_bytes(titleversion, byteorder='little'))
		RDSV=str(RDSV)
		xmlname = str(self._path)	
		xmlname = xmlname[:-4] + '.xml'	
		outfolder = str(ofolder)+'\\'		
		textpath = os.path.join(outfolder, xmlname)
		with open(textpath, 'w+') as tfile:			
			tfile.write('<?xml version="1.0" encoding="utf-8"?>' + '\n')	
			tfile.write('<ContentMeta>' + '\n')	
			tfile.write('  <Type>'+ type +'</Type>' + '\n')	
			tfile.write('  <Id>'+ titleid +'</Id>' + '\n')	
			tfile.write('  <Version>'+ version +'</Version>' + '\n')
			tfile.write('  <RequiredDownloadSystemVersion>'+ RDSV +'</RequiredDownloadSystemVersion>' + '\n')	
			
		for i in range(content_entries):
			vhash = self.read(0x20)
			NcaId = self.read(0x10)
			size = self.read(0x6)
			ncatype = self.readInt8()
			unknown = self.read(0x1)
			if ncatype==0:
				type='Meta'		
			if str(ncatype)=="1":
				type='Program'		
			if ncatype==2:
				type='Data'		
			if ncatype==3:
				type='Control'		
			if ncatype==4:
				type='HtmlDocument'	
			if ncatype==5:
				type='LegalInformation'		
			if ncatype==6:
				type='DeltaFragment'						
				
			NcaId=str(hx(NcaId))
			NcaId=NcaId[2:-1]
			size=str(int.from_bytes(size, byteorder='little'))
			vhash=str(hx(vhash))
			vhash=vhash[2:-1]			
							
			with open(textpath, 'a') as tfile:	
				tfile.write('  <Content>' + '\n')	
				tfile.write('    <Type>'+ type +'</Type>' + '\n')
				tfile.write('    <Id>'+ NcaId +'</Id>' + '\n')
				tfile.write('    <Size>'+ size +'</Size>' + '\n')				
				tfile.write('    <Hash>'+ vhash +'</Hash>' + '\n')	
				tfile.write('    <KeyGeneration>'+ str(self.header.cryptoType2) +'</KeyGeneration>' + '\n')				
				tfile.write('  </Content>' + '\n')						

		self.seek(pfs0_offset+pfs0_size-0x20)			
		digest = str(hx(self.read(0x20)))
		digest=digest[2:-1]			
		original_ID=str(hx(original_ID.to_bytes(8, byteorder='big')))
		original_ID='0x'+original_ID[2:-1]	
		metaname=os.path.basename(os.path.abspath(self._path))
		metaname =  metaname[:-9]
		size=str(os.path.getsize(self._path))		
		with open(textpath, 'a') as tfile:	
			tfile.write('  <Content>' + '\n')	
			tfile.write('    <Type>'+ 'Meta' +'</Type>' + '\n')
			tfile.write('    <Id>'+ metaname +'</Id>' + '\n')
			tfile.write('    <Size>'+ size +'</Size>' + '\n')				
			tfile.write('    <Hash>'+ nsha +'</Hash>' + '\n')				
			tfile.write('    <KeyGeneration>'+ str(keygeneration) +'</KeyGeneration>' + '\n')					
			tfile.write('  </Content>' + '\n')						
			tfile.write('  <Digest>'+ digest +'</Digest>' + '\n')
			tfile.write('  <KeyGenerationMin>'+ str(keygeneration) +'</KeyGenerationMin>' + '\n')
			tfile.write('  <RequiredSystemVersion>'+ str(min_sversion) +'</RequiredSystemVersion>' + '\n')				
			tfile.write('  <OriginalId>'+ original_ID +'</OriginalId>' + '\n')	
			tfile.write('</ContentMeta>')					
		return textpath

	def xml_gen_mod(self,ofolder,nsha,keygeneration):
		file = None
		mode = 'rb'
		crypto1=self.header.getCryptoType()
		crypto2=self.header.getCryptoType2()						
		for f in self:
			cryptoType=f.get_cryptoType()
			cryptoKey=f.get_cryptoKey()	
			cryptoCounter=f.get_cryptoCounter()
		pfs0_offset=0xC00+self.header.get_htable_offset()+self.header.get_pfs0_offset()
		pfs0_size = self.header.get_pfs0_size()		
		super(Nca, self).open(file, mode, cryptoType, cryptoKey, cryptoCounter)
		self.seek(pfs0_offset+0x8)
		pfs0_table_size=self.readInt32()
		cmt_offset=pfs0_offset+0x28+pfs0_table_size
		self.seek(cmt_offset)
		titleid=self.readInt64()
		titleversion = self.read(0x4)
		type_n = self.read(0x1)		
		self.seek(cmt_offset+0xE)
		offset=self.readInt16()
		content_entries=self.readInt16()
		meta_entries=self.readInt16()
		self.seek(cmt_offset+0x18)		
		RDSV=self.readInt64()		
		self.seek(cmt_offset+0x20)
		original_ID=self.readInt64()
		self.seek(cmt_offset+0x28)					
		min_sversion=self.readInt32()
		length_of_emeta=self.readInt32()		
		self.seek(cmt_offset+offset+0x20)
		
		if str(hx(type_n)) == "b'1'":
			type='SystemProgram'		
		if str(hx(type_n)) == "b'2'":
			type='SystemData'
		if str(hx(type_n)) == "b'3'":
			type='SystemUpdate'
		if str(hx(type_n)) == "b'4'":
			type='BootImagePackage'		
		if str(hx(type_n)) == "b'5'":
			type='BootImagePackageSafe'		
		if str(hx(type_n)) == "b'80'":
			type='Application'			
		if str(hx(type_n)) == "b'81'":
			type='Patch'
		if str(hx(type_n)) == "b'82'":
			type='AddOnContent'
		if str(hx(type_n)) == "b'83'":
			type='Delta'

		titleid=str(hx(titleid.to_bytes(8, byteorder='big')))	
		titleid='0x'+titleid[2:-1]
		version = str(int.from_bytes(titleversion, byteorder='little'))
		RDSV=str(RDSV)
		xmlname = str(self._path)	
		xmlname = xmlname[:-4] + '.xml'	
		outfolder = str(ofolder)+'\\'		
		textpath = os.path.join(outfolder, xmlname)
		with open(textpath, 'w+') as tfile:			
			tfile.write('<?xml version="1.0" encoding="utf-8"?>' + '\n')	
			tfile.write('<ContentMeta>' + '\n')	
			tfile.write('  <Type>'+ type +'</Type>' + '\n')	
			tfile.write('  <Id>'+ titleid +'</Id>' + '\n')	
			tfile.write('  <Version>'+ version +'</Version>' + '\n')
			tfile.write('  <RequiredDownloadSystemVersion>'+ RDSV +'</RequiredDownloadSystemVersion>' + '\n')	
			
		for i in range(content_entries):
			vhash = self.read(0x20)
			NcaId = self.read(0x10)
			size = self.read(0x6)
			ncatype = self.readInt8()
			unknown = self.read(0x1)
			if ncatype==0:
				type='Meta'		
			if str(ncatype)=="1":
				type='Program'		
			if ncatype==2:
				type='Data'		
			if ncatype==3:
				type='Control'		
			if ncatype==4:
				type='HtmlDocument'	
			if ncatype==5:
				type='LegalInformation'		
			if ncatype==6:
				type='DeltaFragment'						
				
			NcaId=str(hx(NcaId))
			NcaId=NcaId[2:-1]
			size=str(int.from_bytes(size, byteorder='little'))
			vhash=str(hx(vhash))
			vhash=vhash[2:-1]			
							
			with open(textpath, 'a') as tfile:	
				tfile.write('  <Content>' + '\n')	
				tfile.write('    <Type>'+ type +'</Type>' + '\n')
				tfile.write('    <Id>'+ NcaId +'</Id>' + '\n')
				tfile.write('    <Size>'+ size +'</Size>' + '\n')				
				tfile.write('    <Hash>'+ vhash +'</Hash>' + '\n')	
				tfile.write('    <KeyGeneration>'+ str(self.header.cryptoType2) +'</KeyGeneration>' + '\n')				
				tfile.write('  </Content>' + '\n')						

		self.seek(pfs0_offset+pfs0_size-0x20)			
		digest = str(hx(self.read(0x20)))
		digest=digest[2:-1]			
		original_ID=str(hx(original_ID.to_bytes(8, byteorder='big')))
		original_ID='0x'+original_ID[2:-1]	
		metaname=os.path.basename(os.path.abspath(self._path))
		metaname =  metaname[:-9]
		size=str(os.path.getsize(self._path))		
		with open(textpath, 'a') as tfile:	
			tfile.write('  <Content>' + '\n')	
			tfile.write('    <Type>'+ 'Meta' +'</Type>' + '\n')
			tfile.write('    <Id>'+ metaname +'</Id>' + '\n')
			tfile.write('    <Size>'+ size +'</Size>' + '\n')				
			tfile.write('    <Hash>'+ nsha +'</Hash>' + '\n')				
			tfile.write('    <KeyGeneration>'+ str(keygeneration) +'</KeyGeneration>' + '\n')					
			tfile.write('  </Content>' + '\n')						
			tfile.write('  <Digest>'+ digest +'</Digest>' + '\n')
			tfile.write('  <KeyGeneration>'+ str(keygeneration) +'</KeyGeneration>' + '\n')
			min_sversion=sq_tools.getMinRSV(keygeneration,min_sversion)			
			tfile.write('  <RequiredSystemVersion>'+ str(min_sversion) +'</RequiredSystemVersion>' + '\n')				
			tfile.write('  <OriginalId>'+ original_ID +'</OriginalId>' + '\n')	
			tfile.write('</ContentMeta>')					
		return textpath



		
	def ret_xml(self):
		file = None
		mode = 'rb'
		crypto1=self.header.getCryptoType()
		crypto2=self.header.getCryptoType2()			
		if crypto2>crypto1:
			keygeneration=crypto2
		if crypto2<=crypto1:	
			keygeneration=crypto1		
		xmlname = str(self._path)	
		xmlname = xmlname[:-4] + '.xml'
		metaname=str(self._path)
		metaname =  metaname[:-9]		
		for f in self:
			cryptoType=f.get_cryptoType()
			cryptoKey=f.get_cryptoKey()	
			cryptoCounter=f.get_cryptoCounter()
		pfs0_offset=0xC00+self.header.get_htable_offset()+self.header.get_pfs0_offset()
		pfs0_size = self.header.get_pfs0_size()		
		super(Nca, self).open(file, mode, cryptoType, cryptoKey, cryptoCounter)
		self.seek(pfs0_offset+0x8)
		pfs0_table_size=self.readInt32()
		cmt_offset=pfs0_offset+0x28+pfs0_table_size
		self.seek(cmt_offset)
		titleid=self.readInt64()
		titleversion = self.read(0x4)
		type_n = self.read(0x1)		
		self.seek(cmt_offset+0xE)
		offset=self.readInt16()
		content_entries=self.readInt16()
		meta_entries=self.readInt16()
		self.seek(cmt_offset+0x18)		
		RDSV=self.readInt64()		
		self.seek(cmt_offset+0x20)
		original_ID=self.readInt64()
		self.seek(cmt_offset+0x28)					
		min_sversion=self.readInt32()
		length_of_emeta=self.readInt32()		
		self.seek(cmt_offset+offset+0x20)
		
		if str(hx(type_n)) == "b'1'":
			type='SystemProgram'		
		if str(hx(type_n)) == "b'2'":
			type='SystemData'
		if str(hx(type_n)) == "b'3'":
			type='SystemUpdate'
		if str(hx(type_n)) == "b'4'":
			type='BootImagePackage'		
		if str(hx(type_n)) == "b'5'":
			type='BootImagePackageSafe'		
		if str(hx(type_n)) == "b'80'":
			type='Application'			
		if str(hx(type_n)) == "b'81'":
			type='Patch'
		if str(hx(type_n)) == "b'82'":
			type='AddOnContent'
		if str(hx(type_n)) == "b'83'":
			type='Delta'

		titleid=str(hx(titleid.to_bytes(8, byteorder='big')))	
		titleid='0x'+titleid[2:-1]
		version = str(int.from_bytes(titleversion, byteorder='little'))
		RDSV=str(RDSV)
	
		xml_string = '<?xml version="1.0" encoding="utf-8"?>' + '\n'
		xml_string += '<ContentMeta>' + '\n'
		xml_string +='  <Type>'+ type +'</Type>' + '\n' 
		xml_string +=('  <Id>'+ titleid +'</Id>' + '\n')	
		xml_string +=('  <Version>'+ version +'</Version>' + '\n')
		xml_string +=('  <RequiredDownloadSystemVersion>'+ RDSV +'</RequiredDownloadSystemVersion>' + '\n')	
			
		for i in range(content_entries):
			vhash = self.read(0x20)
			NcaId = self.read(0x10)
			size = self.read(0x6)
			ncatype = self.readInt8()
			unknown = self.read(0x1)
			if ncatype==0:
				type='Meta'		
			if str(ncatype)=="1":
				type='Program'		
			if ncatype==2:
				type='Data'		
			if ncatype==3:
				type='Control'		
			if ncatype==4:
				type='HtmlDocument'	
			if ncatype==5:
				type='LegalInformation'		
			if ncatype==6:
				type='DeltaFragment'						
				
			NcaId=str(hx(NcaId))
			NcaId=NcaId[2:-1]
			size=str(int.from_bytes(size, byteorder='little'))
			vhash=str(hx(vhash))
			vhash=vhash[2:-1]			
							
			xml_string +=('  <Content>' + '\n')	
			xml_string +=('    <Type>'+ type +'</Type>' + '\n')
			xml_string +=('    <Id>'+ NcaId +'</Id>' + '\n')
			xml_string +=('    <Size>'+ size +'</Size>' + '\n')				
			xml_string +=('    <Hash>'+ vhash +'</Hash>' + '\n')	
			xml_string +=('    <KeyGeneration>'+ str(keygeneration) +'</KeyGeneration>' + '\n')				
			xml_string +=('  </Content>' + '\n')						

		self.seek(pfs0_offset+pfs0_size-0x20)			
		digest = str(hx(self.read(0x20)))
		digest=digest[2:-1]			
		original_ID=str(hx(original_ID.to_bytes(8, byteorder='big')))
		original_ID='0x'+original_ID[2:-1]	
		size=str(os.path.getsize(self._path))	
		
		xml_string +=('  <Content>' + '\n')	
		xml_string +=('    <Type>'+ 'Meta' +'</Type>' + '\n')
		xml_string +=('    <Id>'+ metaname +'</Id>' + '\n')
		xml_string +=('    <Size>'+ size +'</Size>' + '\n')				
		xml_string +=('    <Hash>'+ nsha +'</Hash>' + '\n')				
		xml_string +=('    <KeyGeneration>'+ str(keygeneration) +'</KeyGeneration>' + '\n')					
		xml_string +=('  </Content>' + '\n')						
		xml_string +=('  <Digest>'+ digest +'</Digest>' + '\n')
		xml_string +=('  <KeyGeneration>'+ str(keygeneration) +'</KeyGeneration>' + '\n')
		xml_string +=('  <RequiredSystemVersion>'+ str(min_sversion) +'</RequiredSystemVersion>' + '\n')				
		xml_string +=('  <OriginalId>'+ original_ID +'</OriginalId>' + '\n')	
		xml_string +=('</ContentMeta>')	
		
		#print(xml_string)
		
		size=len(xml_string)
		
		return xmlname,size,xml_string
		
			
	def printInfo(self, indent = 0):
		tabs = '\t' * indent
		Print.info('\n%sNCA Archive\n' % (tabs))
		super(Nca, self).printInfo(indent)
#		Print.info(tabs + 'Header Block Hash: ' + str(hx(self.header.get_hblock_hash())))
#		self.header.calculate_hblock_hash()
#		self.get_hblock()
#		self.calc_htable_hash()
#		Print.info('hash from pfs0: ' + str(hx(self.get_pfs0_hash())))
#		self.calc_pfs0_hash()
#		self.get_req_system()
#		Print.info(tabs + 'RSA-2048 signature 1 = ' + str(hx(self.header.signature1)))
#		Print.info(tabs + 'RSA-2048 signature 2 = ' + str(hx(self.header.signature2)))
		Print.info(tabs + 'magic = ' + str(self.header.magic))
		Print.info(tabs + 'titleId = ' + str(self.header.titleId))
		Print.info(tabs + 'rightsId = ' + str(self.header.rightsId))
		Print.info(tabs + 'isGameCard = ' + hex(self.header.isGameCard))
		Print.info(tabs + 'contentType = ' + str(self.header.contentType))
		#Print.info(tabs + 'cryptoType = ' + str(self.header.getCryptoType()))
		Print.info(tabs + 'SDK version = ' + self.get_sdkversion())
		Print.info(tabs + 'Size: ' + str(self.header.size))
		Print.info(tabs + 'Crypto-Type1: ' + str(self.header.cryptoType))
		Print.info(tabs + 'Crypto-Type2: ' + str(self.header.cryptoType2))
		Print.info(tabs + 'key Index: ' + str(self.header.keyIndex))
		#Print.info(tabs + 'key Block: ' + str(self.header.getKeyBlock()))
		for key in self.header.keys:
			Print.info(tabs + 'key Block: ' + str(hx(key)))
		
		Print.info('\n%sPartitions:' % (tabs))
		
		for s in self:
			s.printInfo(indent+1)
			
		#self.read_pfs0_header()	
		#self.read_cnmt()


	def ncalist_bycnmt(self, file = None, mode = 'rb'):
		for f in self:
			cryptoType=f.get_cryptoType()
			cryptoKey=f.get_cryptoKey()	
			cryptoCounter=f.get_cryptoCounter()
		pfs0_offset=0xC00+self.header.get_htable_offset()+self.header.get_pfs0_offset()
		pfs0_size = self.header.get_pfs0_size()		
		super(Nca, self).open(file, mode, cryptoType, cryptoKey, cryptoCounter)
		self.seek(pfs0_offset+0x8)
		pfs0_table_size=self.readInt32()
		cmt_offset=pfs0_offset+0x28+pfs0_table_size
		self.seek(cmt_offset)
		titleid=self.readInt64()
		titleversion = self.read(0x4)
		type_n = self.read(0x1)		
		self.seek(cmt_offset+0xE)
		offset=self.readInt16()
		content_entries=self.readInt16()
		meta_entries=self.readInt16()
		self.seek(cmt_offset+0x20)
		original_ID=self.readInt64()
		self.seek(cmt_offset+0x28)					
		min_sversion=self.readInt32()
		length_of_emeta=self.readInt32()			
		self.seek(cmt_offset+offset+0x20)
		ncalist=list()
		for i in range(content_entries):
			vhash = self.read(0x20)
			NcaId = self.read(0x10)
			size = self.read(0x6)
			ncatype = self.read(0x1)
			unknown = self.read(0x1)
			nca2append=str(hx(NcaId))
			nca2append=nca2append[2:-1]+'.nca'
			ncalist.append(nca2append)
		nca_meta=str(self._path)	
		ncalist.append(nca_meta)
		return ncalist

	def copy_files(self,buffer,ofolder=False,filepath=False,io=0,eo=False):
		i=0
		if ofolder == False:
			outfolder = 'ofolder'
			if not os.path.exists(outfolder):
				os.makedirs(outfolder)
		for f in self:
			if filepath==False:
				filename =  str(i)
				i+=1
				filepath = os.path.join(outfolder, filename)
				fp = open(filepath, 'w+b')
			self.rewind();f.seek(io)
			for data in iter(lambda: f.read(int(buffer)), ""):
				fp.write(data)
				fp.flush()
				if not data:
					fp.close()
					break	
					
	def get_nacp_offset(self):
		for f in self:
			self.rewind()					
			f.rewind()	
			Langue = list()	
			Langue = [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14]
			SupLg=list()
			regionstr=""
			offset=0x14200
			for i in Langue:
				try:
					f.seek(offset+i*0x300)
					test=f.read(0x200)
					test = test.split(b'\0', 1)[0].decode('utf-8')
					test = (re.sub(r'[\/\\]+', ' ', test))
					test = test.strip()
					test2=f.read(0x100)
					test2 = test2.split(b'\0', 1)[0].decode('utf-8')
					test2 = (re.sub(r'[\/\\]+', ' ', test2))
					test2 = test2.strip()					
					if test == "" or test2 == "":	
						offset=0x14400
						f.seek(offset+i*0x300)
						test=f.read(0x200)
						test = test.split(b'\0', 1)[0].decode('utf-8')
						test = (re.sub(r'[\/\\]+', ' ', test))
						test = test.strip()	
						test2=f.read(0x100)
						test2 = test2.split(b'\0', 1)[0].decode('utf-8')
						test2 = (re.sub(r'[\/\\]+', ' ', test2))
						test2 = test2.strip()							
						if test == "" or test2 == "":					
							offset=0x14000
							while offset<=(0x14200+i*0x300):
								offset=offset+0x100
								f.seek(offset+i*0x300)
								test=f.read(0x200)
								test = test.split(b'\0', 1)[0].decode('utf-8')
								test = (re.sub(r'[\/\\]+', ' ', test))
								test = test.strip()
								test2=f.read(0x100)
								test2 = test2.split(b'\0', 1)[0].decode('utf-8')
								test2 = (re.sub(r'[\/\\]+', ' ', test2))
								test2 = test2.strip()										
								if test != "" and test2 != "" :	
									offset=offset
									break
							if test != "":	
								offset=offset
								break			
						if test != "":	
							offset=offset
							break								
					else:
						break
				except:
					pass
			try:		
				f.seek(offset+0x3060)
				ediver = f.read(0x10)
				#print('here2')
				#print(hx(ediver))
				try:
					ediver = ediver.split(b'\0', 1)[0].decode('utf-8')
					ediver = (re.sub(r'[\/\\]+', ' ', ediver))
					ediver = ediver.strip()	
				except:
					offset=0x16900-0x300*14
					f.seek(offset+0x3060)
					ediver = f.read(0x10)
					ediver = ediver.split(b'\0', 1)[0].decode('utf-8')
					ediver = (re.sub(r'[\/\\]+', ' ', ediver))
					ediver = ediver.strip()						
				try:  
					int(ediver[0])+1
				except:
					ediver="-"
				if ediver == '-':
					for i in Langue:
						try:
							i=i+1
							offset2=offset-0x300*i
							f.seek(offset2+0x3060)			
							ediver = f.read(0x10)
							ediver = ediver.split(b'\0', 1)[0].decode('utf-8')
							ediver = (re.sub(r'[\/\\]+', ' ', ediver))
							ediver = ediver.strip()	
							try:  
								int(ediver[0])+1
								offset=offset2
								break
							except:
								ediver="-"	
						except:
							pass		
				if ediver == '-':
					try:
						while (offset2+0x3060)<=0x18600:
							offset2+=0x100
							f.seek(offset2+0x3060)	
							ediver = f.read(0x10)
							ediver = ediver.split(b'\0', 1)[0].decode('utf-8')
							ediver = (re.sub(r'[\/\\]+', ' ', ediver))
							ediver = ediver.strip()	
							if ediver != '':
								if str(ediver[0])!='v' and str(ediver[0])!='V':
									try:  
										int(ediver[0])+1
										offset=offset2
										break
									except:
										ediver="-"
										break		
					except:
						ediver="-"		
			except:
				pass
			f.seek(offset)
			#data=f.read()
		return offset
					
					
	def get_langueblock(self,title,roman=True):
		for f in self:
			self.rewind()					
			f.rewind()	
			Langue = list()	
			Langue = [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14]
			SupLg=list()
			regionstr=""
			offset=0x14200
			for i in Langue:
				try:
					f.seek(offset+i*0x300)
					test=f.read(0x200)
					test = test.split(b'\0', 1)[0].decode('utf-8')
					test = (re.sub(r'[\/\\]+', ' ', test))
					test = test.strip()
					test2=f.read(0x100)
					test2 = test2.split(b'\0', 1)[0].decode('utf-8')
					test2 = (re.sub(r'[\/\\]+', ' ', test2))
					test2 = test2.strip()					
					if test == "" or test2 == "":	
						offset=0x14400
						f.seek(offset+i*0x300)
						test=f.read(0x200)
						test = test.split(b'\0', 1)[0].decode('utf-8')
						test = (re.sub(r'[\/\\]+', ' ', test))
						test = test.strip()	
						test2=f.read(0x100)
						test2 = test2.split(b'\0', 1)[0].decode('utf-8')
						test2 = (re.sub(r'[\/\\]+', ' ', test2))
						test2 = test2.strip()							
						if test == "" or test2 == "":					
							offset=0x14000
							while offset<=(0x14200+i*0x300):
								offset=offset+0x100
								f.seek(offset+i*0x300)
								test=f.read(0x200)
								test = test.split(b'\0', 1)[0].decode('utf-8')
								test = (re.sub(r'[\/\\]+', ' ', test))
								test = test.strip()
								test2=f.read(0x100)
								test2 = test2.split(b'\0', 1)[0].decode('utf-8')
								test2 = (re.sub(r'[\/\\]+', ' ', test2))
								test2 = test2.strip()										
								if test != "" and test2 != "" :	
									offset=offset
									break
							if test != "":	
								offset=offset
								break			
						if test != "":	
							offset=offset
							break								
					else:
						break
				except:
					pass
			try:		
				f.seek(offset+0x3060)
				ediver = f.read(0x10)
				#print('here2')
				#print(hx(ediver))
				try:
					ediver = ediver.split(b'\0', 1)[0].decode('utf-8')
					ediver = (re.sub(r'[\/\\]+', ' ', ediver))
					ediver = ediver.strip()	
				except:
					offset=0x16900-0x300*14
					f.seek(offset+0x3060)
					ediver = f.read(0x10)
					ediver = ediver.split(b'\0', 1)[0].decode('utf-8')
					ediver = (re.sub(r'[\/\\]+', ' ', ediver))
					ediver = ediver.strip()						
				try:  
					int(ediver[0])+1
				except:
					ediver="-"
				if ediver == '-':
					for i in Langue:
						try:
							i=i+1
							offset2=offset-0x300*i
							f.seek(offset2+0x3060)			
							ediver = f.read(0x10)
							ediver = ediver.split(b'\0', 1)[0].decode('utf-8')
							ediver = (re.sub(r'[\/\\]+', ' ', ediver))
							ediver = ediver.strip()	
							try:  
								int(ediver[0])+1
								offset=offset2
								break
							except:
								ediver="-"	
						except:
							pass								
				if ediver == '-':
					try:
						while (offset2+0x3060)<=0x18600:
							offset2+=0x100
							f.seek(offset2+0x3060)	
							ediver = f.read(0x10)
							ediver = ediver.split(b'\0', 1)[0].decode('utf-8')
							ediver = (re.sub(r'[\/\\]+', ' ', ediver))
							ediver = ediver.strip()	
							if ediver != '':
								if str(ediver[0])!='v' and str(ediver[0])!='V':
									try:  
										int(ediver[0])+1
										offset=offset2
										break
									except:
										ediver="-"
										break		
					except:
						ediver="-"
						
			except:
				pass
			Langue = [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14]				
			for i in Langue:
				try:
					f.seek(offset+i*0x300)	
					title = f.read(0x200)		
					title = title.split(b'\0', 1)[0].decode('utf-8')
					title = (re.sub(r'[\/\\]+', ' ', title))
					title = title.strip()
					if title != "":	
						if i==0:
							SupLg.append("US (eng)")
							regionstr+='1|'
						if i==1:
							SupLg.append("UK (eng)")
							regionstr+='1|'							
						if i==2:
							SupLg.append("JP")
							regionstr+='1|'							
						if i==3:
							SupLg.append("FR")	
							regionstr+='1|'					
						if i==4:
							SupLg.append("DE")
							regionstr+='1|'			
						if i==5:
							SupLg.append("LAT (spa)")	
							regionstr+='1|'						
						if i==6:
							SupLg.append("SPA")	
							regionstr+='1|'				
						if i==7:
							SupLg.append("IT")	
							regionstr+='1|'							
						if i==8:
							SupLg.append("DU")	
							regionstr+='1|'					
						if i==9:
							SupLg.append("CAD (fr)")
							regionstr+='1|'						
						if i==10:
							SupLg.append("POR")	
							regionstr+='1|'						
						if i==11:
							SupLg.append("RU")	
							regionstr+='1|'					
						if i==12:
							SupLg.append("KOR")	
							regionstr+='1|'			
						if i==13:
							SupLg.append("TW (ch)")		
							regionstr+='1|'			
						if i==14:
							SupLg.append("CH")	
							regionstr+='1|'
					else:
						regionstr+='0|'	
				except:
					pass
			Langue = [0,1,6,5,7,10,3,4,9,8,2,11,12,13,14]						
			for i in Langue:
				try:
					f.seek(offset+i*0x300)		
					title = f.read(0x200)
					editor = f.read(0x100)							
					title = title.split(b'\0', 1)[0].decode('utf-8')
					title = (re.sub(r'[\/\\]+', ' ', title))
					title = title.strip()
					editor = editor.split(b'\0', 1)[0].decode('utf-8')
					editor = (re.sub(r'[\/\\]+', ' ', editor))
					editor = editor.strip()							
					if title == "":
						title = 'DLC'
					if title != 'DLC':
						title = title
						f.seek(offset+0x3060)	
						ediver = f.read(0x10)
						ediver = ediver.split(b'\0', 1)[0].decode('utf-8')
						ediver = (re.sub(r'[\/\\]+', ' ', ediver))
						ediver = ediver.strip()	
						if ediver == '':
							try:
								while (offset+0x3060)<=0x18600:
									offset+=0x100
									f.seek(offset+0x3060)	
									ediver = f.read(0x10)
									ediver = ediver.split(b'\0', 1)[0].decode('utf-8')
									ediver = (re.sub(r'[\/\\]+', ' ', ediver))
									ediver = ediver.strip()	
									if ediver != '':
										if str(ediver[0])!='v' and str(ediver[0])!='V':
											try:  
												int(ediver[0])+1
												break
											except:
												ediver="-"
												break		
							except:
								ediver="-"
						f.seek(offset+0x3028)	
						isdemo = f.readInt8('little')
						if ediver !='-':
							if isdemo == 0:
								isdemo = 0
							elif isdemo == 1:
								isdemo = 1
							elif isdemo == 2:
								isdemo = 2
							else:
								isdemo = 0
						else:
							isdemo = 0
						if i == 2:	
							if roman == True:
								kakasi = pykakasi.kakasi()
								kakasi.setMode("H", "a")
								kakasi.setMode("K", "a")
								kakasi.setMode("J", "a")
								kakasi.setMode("s", True)
								kakasi.setMode("E", "a")
								kakasi.setMode("a", None)
								kakasi.setMode("C", False)
								converter = kakasi.getConverter()
								title=converter.do(title)	
								title=title[0].upper()+title[1:]
								editor=converter.do(editor)		
								editor=editor[0].upper()+editor[1:]	
							else:pass		
						if i == 14 or i == 13 or i==12:	
							if roman == True:						
								kakasi = pykakasi.kakasi()
								kakasi.setMode("H", "a")
								kakasi.setMode("K", "a")
								kakasi.setMode("J", "a")
								kakasi.setMode("s", True)
								kakasi.setMode("E", "a")
								kakasi.setMode("a", None)
								kakasi.setMode("C", False)
								converter = kakasi.getConverter()
								title=converter.do(title)	
								title=title[0].upper()+title[1:]
								editor=converter.do(editor)		
								editor=editor[0].upper()+editor[1:]	
							else:pass									
						title=re.sub(' +', ' ',title)
						editor=re.sub(' +', ' ',editor)
						return(title,editor,ediver,SupLg,regionstr[:-1],isdemo)
				except:
					pass
		regionstr="0|0|0|0|0|0|0|0|0|0|0|0|0|0"		
		ediver='-'		
		return(title,"",ediver,"",regionstr,"")			

	def get_sdkversion(self):		
		sdkversion=str(self.header.sdkVersion4)+'.'+str(self.header.sdkVersion3)+'.'+str(self.header.sdkVersion2)+'.'+str(self.header.sdkVersion1)	
		return sdkversion

	def verify(self,feed,targetkg=False,endcheck=False,progress=False,bar=False):	
		if feed == False:
			feed=''
		indent='    > '
		if self._path.endswith('cnmt.nca'):	
			arrow='   -> '
		else:
			arrow=tabs+'  -> ' 		
		self.rewind()	
		#print('Signature 1:')
		sign1 = self.header.signature1
		#Hex.dump(sign1)		
		#print('')			
		#print('Header data:')	
		hcrypto = aes128.AESXTS(uhx(Keys.get('header_key')))
		self.header.rewind()
		orig_header= self.header.read(0xC00)	
		self.header.seek(0x200)	
		headdata = self.header.read(0x200)	
		#print(hx(orig_header))
		#Hex.dump(headdata)
		pubkey=RSA.RsaKey(n=nca_header_fixed_key_modulus, e=RSA_PUBLIC_EXPONENT)
		rsapss = PKCS1_PSS.new(pubkey)
		digest = SHA256.new(headdata)
		verification=rsapss.verify(digest, sign1)
		crypto1=self.header.getCryptoType()
		crypto2=self.header.getCryptoType2()	
		if crypto2>crypto1:
			masterKeyRev=crypto2
		if crypto2<=crypto1:
			masterKeyRev=crypto1		
		currkg=masterKeyRev		
		if verification == True:
			message=(indent+self._path+arrow+'is PROPER');print(message);feed+=message+'\n'			
			#print(hx(headdata))		
			return True,False,self._path,feed,currkg,False,False,self.header.getgamecard()
		else:
			crypto = aes128.AESECB(Keys.keyAreaKey(Keys.getMasterKeyIndex(masterKeyRev), self.header.keyIndex))			
			KB1L=self.header.getKB1L()
			KB1L = crypto.decrypt(KB1L)
			if sum(KB1L) != 0:						
				#print(hx(headdata))			
				checkrights,kgchg,titlekey,tr,headdata,orkg=self.restorehead_tr()
				if headdata != False:
					orig_header=orig_header[0x00:0x200]+headdata+orig_header[0x400:]
					#print(hx(orig_header))
					orig_header=hcrypto.encrypt(orig_header)
				else:
					orig_header = False						
				if checkrights == True:
					message=(indent+self._path+arrow+'is PROPER');print(message);feed+=message+'\n'				
					message=(tabs+'* '+"TITLERIGHTS WERE REMOVED");print(message);feed+=message+'\n'			
					if kgchg == False:
						message=(tabs+'* '+"Original titlerights id is : "+(str(hx(tr)).upper())[2:-1]);print(message);feed+=message+'\n'						
						message=(tabs+'* '+"Original titlekey is       : "+(str(hx(titlekey)).upper())[2:-1]);print(message);feed+=message+'\n'						
						tcheck=(str(hx(titlekey)).upper())[2:-1]		
						if tcheck == '00000000000000000000000000000000':
							message=(tabs+'* '+"WARNING: sum(titlekey)=0 -> S.C. conversion may be incorrect and come from nsx file");print(message);feed+=message+'\n'										
					elif kgchg == True:
						message=(tabs+'* '+"KEYGENERATION WAS CHANGED FROM "+str(orkg)+" TO "+str(currkg));print(message);feed+=message+'\n'		
						message=(tabs+'* '+"Original titlerights id is -> "+(str(hx(tr)).upper())[2:-1]);print(message);feed+=message+'\n'		
						message=(tabs+'* '+"Original titlekey is -> "+(str(hx(titlekey)).upper())[2:-1]);print(message);feed+=message+'\n'	
						tcheck=(str(hx(titlekey)).upper())[2:-1]
						if tcheck == '00000000000000000000000000000000':
							message=(tabs+'* '+"WARNING: sum(titlekey)=0 -> S.C. conversion may be incorrect and come from nsx file");print(message);feed+=message+'\n'										
					return True,orig_header,self._path,feed,orkg,tr,titlekey,self.header.getgamecard()	
				else:
					message=(indent+self._path+arrow+'was MODIFIED');print(message);feed+=message+'\n'		
					message=(tabs+'* '+"NOT VERIFIABLE COULD'VE BEEN TAMPERED WITH");print(message);feed+=message+'\n'			
					return False,False,self._path,feed,False,False,False,self.header.getgamecard()	
			else:
				if targetkg != False:
					if self.header.contentType == Type.Content.META:
						ver,kgchg,cardchange,headdata,orkg=self.verify_cnmt_withkg(targetkg)					
				else:
					ver,kgchg,cardchange,headdata,orkg=self.restorehead_ntr()				
				if headdata != False:
					orig_header=orig_header[0x00:0x200]+headdata+orig_header[0x400:]
					#print(hx(orig_header))
					orig_header=hcrypto.encrypt(orig_header)					
				else:
					orig_header = False				
				if ver == True:
					chkkg=currkg
					if targetkg == False:
						message=(indent+self._path+arrow+'is PROPER');print(message);feed+=message+'\n'	
					else:
						if progress != False:
							message=(tabs+'* '+"ORIGIN OF CNMT FILE IS PROPER");bar.write(message);feed+=message+'\n'	
						else:
							message=(tabs+'* '+"ORIGIN OF CNMT FILE IS PROPER");print(message);feed+=message+'\n'					
					if kgchg == True:
						if progress != False:
							message=(tabs+'* '+"KEYGENERATION WAS CHANGED FROM "+str(orkg)+" TO "+str(currkg));bar.write(message);feed+=message+'\n'	
						else:
							message=(tabs+'* '+"KEYGENERATION WAS CHANGED FROM "+str(orkg)+" TO "+str(currkg));print(message);feed+=message+'\n'	
						chkkg=orkg	
					if cardchange == True:				
						if self.header.getgamecard() != 0:
							if progress != False:
								message=(tabs+'* '+"ISGAMECARD WAS CHANGED FROM 0 TO 1");bar.write(message);feed+=message+'\n'								
							else:
								message=(tabs+'* '+"ISGAMECARD WAS CHANGED FROM 0 TO 1");print(message);feed+=message+'\n'	
						else:
							if progress != False:
								message=(tabs+'* '+"ISGAMECARD WAS CHANGED FROM 1 TO 0");bar.write(message);feed+=message+'\n'								
							else:						
								message=(tabs+'* '+"ISGAMECARD WAS CHANGED FROM 1 TO 0");print(message);feed+=message+'\n'									
					return True,orig_header,self._path,feed,chkkg,False,False,self.header.getgamecard()		
				else:
					if self.header.contentType == Type.Content.META:
						if targetkg == False:
							if os.path.exists(self._path):
								printname=str(os.path.basename(os.path.abspath(self._path)))
							else:
								printname=str(self._path)											
							if progress != False:					
								pass
							else:	
								message=(indent+self._path+arrow+'needs RSV check');print(message);feed+=message+'\n'	
								message=(tabs+'* '+"CHECKING INTERNAL HASHES");print(message);feed+=message+'\n'	
							if progress == False:							
								feed,correct=self.check_cnmt_hashes(feed)						
								if correct == True:
									if progress != False:						
										message=(tabs+'* '+"INTERNAL HASHES MATCH");bar.write(message);feed+=message+'\n'
									else:	
										message=(tabs+'* '+"INTERNAL HASHES MATCH");print(message);feed+=message+'\n'							
								if correct == False:
									if progress != False:							
										message=(tabs+'* '+"INTERNAL HASH MISSMATCH");bar.write(message);feed+=message+'\n'	
										message=(tabs+'* '+"BAD CNMT FILE!!!");bar.write(message);feed+=message+'\n'
									else:									
										message=(tabs+'* '+"INTERNAL HASH MISSMATCH");print(message);feed+=message+'\n'	
										message=(tabs+'* '+"BAD CNMT FILE!!!");print(message);feed+=message+'\n'				
									return 'BADCNMT',False,self._path,feed,False,False,False,self.header.getgamecard()							
						else:	
							if endcheck == False:
								pass
							elif endcheck == True:
								if os.path.exists(self._path):
									printname=str(os.path.basename(os.path.abspath(self._path)))
								else:
									printname=str(self._path)									
								if progress != False:							
									message=(indent+printname+arrow+'was MODIFIED');bar.write(message);feed+=message+'\n'	
									message=(tabs+'* '+"NOT VERIFIABLE!!!");bar.write(message);feed+=message+'\n'
								else:									
									message=(indent+self._path+arrow+'was MODIFIED');print(message);feed+=message+'\n'		
									message=(tabs+'* '+"NOT VERIFIABLE!!!");print(message);feed+=message+'\n'							
						return False,False,self._path,feed,False,False,False,self.header.getgamecard()				
					else:
						if os.path.exists(self._path):
							printname=str(os.path.basename(os.path.abspath(self._path)))
						else:
							printname=str(self._path)						
						if progress != False:							
							message=(indent+printname+arrow+'was MODIFIED');bar.write(message);feed+=message+'\n'	
							message=(tabs+'* '+"NOT VERIFIABLE!!!");bar.write(message);feed+=message+'\n'
						else:									
							message=(indent+self._path+arrow+'was MODIFIED');print(message);feed+=message+'\n'		
							message=(tabs+'* '+"NOT VERIFIABLE!!!");print(message);feed+=message+'\n'							
						return False,False,self._path,feed,False,False,False,self.header.getgamecard()						
			if progress != False:
				message=(indent+self._path+arrow+'was MODIFIED');bar.write(message);feed+=message+'\n'			
				message=(tabs+'* '+"NOT VERIFIABLE!!!");bar.write(message);feed+=message+'\n'							
			else:	
				message=(indent+self._path+arrow+'was MODIFIED');print(message);feed+=message+'\n'			
				message=(tabs+'* '+"NOT VERIFIABLE!!!");print(message);feed+=message+'\n'				
			return False,False,self._path,feed,False,False,False,self.header.getgamecard()		
			
	def verify_cnmt_withkg(self,targetkg):	
		targetkg=int(targetkg)	
		sign1 = self.header.signature1		
		self.header.seek(0x200)	
		headdata = self.header.read(0x200)
		card='01';card=bytes.fromhex(card)
		eshop='00';eshop=bytes.fromhex(eshop)
		#print(hx(headdata))
		#Hex.dump(headdata)				
		pubkey=RSA.RsaKey(n=nca_header_fixed_key_modulus, e=RSA_PUBLIC_EXPONENT)
		rsapss = PKCS1_PSS.new(pubkey)
		digest = SHA256.new(headdata)
		verification=rsapss.verify(digest, sign1)	
		crypto1=self.header.getCryptoType()
		crypto2=self.header.getCryptoType2()	
		if crypto2>crypto1:
			masterKeyRev=crypto2
		if crypto2<=crypto1:	
			masterKeyRev=crypto1	
		if	self.header.getgamecard() == 0:		
			headdata2 = b''
			headdata2=headdata[0x00:0x04]+eshop+headdata[0x05:]		
			digest2 = SHA256.new(headdata2)	
			verification2=rsapss.verify(digest2, sign1)
			if verification2 == True:
				return True,False,False,headdata2,masterKeyRev	
			else:	
				headdata2 = b''
				headdata2=headdata[0x00:0x04]+card+headdata[0x05:]		
				digest2 = SHA256.new(headdata2)	
				verification2=rsapss.verify(digest2, sign1)	
				if verification2 == True:
					return True,False,True,headdata2,masterKeyRev					
		else:
			headdata2 = b''
			headdata2=headdata[0x00:0x04]+eshop+headdata[0x05:]	
			digest2 = SHA256.new(headdata2)
			verification2=rsapss.verify(digest2, sign1)			
			if verification2 == True:
				return True,False,True,headdata2,masterKeyRev	
			else:	
				headdata2 = b''
				headdata2=headdata[0x00:0x04]+card+headdata[0x05:]		
				digest2 = SHA256.new(headdata2)	
				verification2=rsapss.verify(digest2, sign1)	
				if verification2 == True:
					return True,False,False,headdata2,masterKeyRev					
				
		key = Keys.keyAreaKey(Keys.getMasterKeyIndex(masterKeyRev), self.header.keyIndex)				
		crypto = aes128.AESECB(key)
		encKeyBlock = self.header.getKeyBlock()
		decKeyBlock = crypto.decrypt(encKeyBlock)				
		newMasterKeyRev=targetkg
		key = Keys.keyAreaKey(Keys.getMasterKeyIndex(newMasterKeyRev), self.header.keyIndex)				
		crypto = aes128.AESECB(key)
		reEncKeyBlock = crypto.encrypt(decKeyBlock)		
		i=targetkg
		if i<3:
			crypto1='0'+str(i)
			crypto2='00'
		else:
			crypto1='02'
			crypto2='0'+str(i)	
		crypto1=bytes.fromhex(crypto1);crypto2=bytes.fromhex(crypto2)				
		headdata1 = b''				
		headdata1=headdata[0x00:0x04]+card+headdata[0x05:0x06]+crypto1+headdata[0x07:0x20]+crypto2+headdata[0x21:0x100]+reEncKeyBlock+headdata[0x140:]
		#print(hx(headdata1))
		headdata2 = b''
		headdata2=headdata[0x00:0x04]+eshop+headdata1[0x05:]	
		#print(hx(headdata2))
		digest1 = SHA256.new(headdata1)
		digest2 = SHA256.new(headdata2)
		verification1=rsapss.verify(digest1, sign1)		
		verification2=rsapss.verify(digest2, sign1)	
		if verification1 == True:
			if	self.header.getgamecard() == 0:					
				return True,True,True,headdata1,newMasterKeyRev
			else:
				return True,True,False,headdata1,newMasterKeyRev				
		if verification2 == True:
			if	self.header.getgamecard() == 0:					
				return True,True,False,headdata2,newMasterKeyRev	
			else:				
				return True,True,True,headdata2,newMasterKeyRev						
		return False,False,False,False,masterKeyRev	
			
	def check_cnmt_hashes(self,feed):		
		sha=self.calc_pfs0_hash()
		sha_get=self.calc_pfs0_hash()	
		correct=True
		if sha == sha_get:
			message=(tabs+'  '+"  - PFS0 hash is CORRECT");print(message);feed+=message+'\n'
			#print(hx(sha))			
			#print(hx(sha_get))
		else:
			message=(tabs+'  '+"  - PFS0 hash is INCORRECT!!!");print(message);feed+=message+'\n'		
			#print(hx(sha))				
			#print(hx(sha_get))		
			correct=False	
		sha2=self.calc_htable_hash()	
		sha2_get=self.calc_htable_hash()
		if sha2 == sha2_get:
			message=(tabs+'  '+"  - HASH TABLE hash is CORRECT");print(message);feed+=message+'\n'	
			#print(hx(sha2))				
			#print(hx(sha2_get))
		else:
			message=(tabs+'  '+"  - HASH TABLE hash is INCORRECT!!!");print(message);feed+=message+'\n'	
			#print(hx(sha2))				
			#print(hx(sha2_get))
			correct=False			
		sha3=self.header.calculate_hblock_hash()	
		sha3_get=self.header.calculate_hblock_hash()
		if sha3 == sha3_get:
			message=(tabs+'  '+"  - HEADER BLOCK hash is CORRECT");print(message);feed+=message+'\n'			
			#print(hx(sha3))				
			#print(hx(sha3_get))			
		else:
			message=(tabs+'  '+"  - HEADER BLOCK hash is INCORRECT!!!");print(message);feed+=message+'\n'				
			#print(hx(sha3))				
			#print(hx(sha3_get))
			correct=False			
		return feed,correct			
			
	def restorehead_tr(self):	
		sign1 = self.header.signature1	
		crypto1=self.header.getCryptoType()
		crypto2=self.header.getCryptoType2()		
		nca_id=self.header.titleId	
		tr=nca_id+'000000000000000'+str(crypto2)	
		tr=bytes.fromhex(tr)				
		if crypto1>crypto2:
			masterKeyRev = crypto1
		else:
			masterKeyRev = crypto2		

		encKeyBlock = self.header.getKeyBlock()
		key = Keys.keyAreaKey(Keys.getMasterKeyIndex(masterKeyRev), self.header.keyIndex)		
		crypto = aes128.AESECB(key)
		decKeyBlock = crypto.decrypt(encKeyBlock[:16])			
		titleKeyEnc = Keys.encryptTitleKey(decKeyBlock, Keys.getMasterKeyIndex(masterKeyRev))

		self.header.seek(0x200)	
		headdata = b''
		headdata += self.header.read(0x30)
		headdata += tr
		self.header.read(0x10)
		headdata += self.header.read(0x100-0x40)		
		headdata += bytes.fromhex('00'*0x10*4)			
		self.header.seek(0x340)	
		headdata += self.header.read(0x100-0x40)		
		#print(hx(headdata))
		#Hex.dump(headdata)				
		pubkey=RSA.RsaKey(n=nca_header_fixed_key_modulus, e=RSA_PUBLIC_EXPONENT)
		rsapss = PKCS1_PSS.new(pubkey)
		digest = SHA256.new(headdata)
		verification=rsapss.verify(digest, sign1)		
		if verification == True:
			return True,False,titleKeyEnc,tr,headdata,masterKeyRev
		else:
			tr2=nca_id[:-3]+'800000000000000000'+str(crypto2)	
			tr2=bytes.fromhex(tr2)
			headdata2 = b''
			headdata2=headdata[0x00:0x30]+tr2+headdata[0x40:]
			digest2 = SHA256.new(headdata2)
			verification=rsapss.verify(digest2, sign1)	
			if verification == True:
				return True,False,titleKeyEnc,tr2,headdata2,masterKeyRev			
			else:
				nlist=list()
				for i in range(9):
					nlist.append(i)
				sorted(nlist, key=int, reverse=True)		
				for i in nlist:
					if i<3:
						crypto1='0'+str(i)
						crypto2='00'
					else:
						crypto1='02'
						crypto2='0'+str(i)	
					masterKeyRev = i	
					encKeyBlock = self.header.getKeyBlock()
					key = Keys.keyAreaKey(Keys.getMasterKeyIndex(masterKeyRev), self.header.keyIndex)		
					crypto = aes128.AESECB(key)
					decKeyBlock = crypto.decrypt(encKeyBlock[:16])			
					titleKeyEnc = Keys.encryptTitleKey(decKeyBlock, Keys.getMasterKeyIndex(masterKeyRev))		
					
					tr1=nca_id+'000000000000000'+str(crypto2[1])					
					tr2=nca_id[:-3]+'800000000000000000'+str(crypto2[1])
					tr1=bytes.fromhex(tr1);tr2=bytes.fromhex(tr2)
					crypto1=bytes.fromhex(crypto1);crypto2=bytes.fromhex(crypto2)
					headdata1 = b''
					headdata1=headdata[0x00:0x06]+crypto1+headdata[0x07:0x20]+crypto2+headdata[0x21:0x30]+tr1+headdata[0x40:]
					headdata2 = b''
					headdata2=headdata1[0x00:0x30]+tr2+headdata[0x40:]		
					digest1 = SHA256.new(headdata1)
					digest2 = SHA256.new(headdata2)
					verification1=rsapss.verify(digest1, sign1)		
					verification2=rsapss.verify(digest2, sign1)		
					if verification1 == True:
						return True,True,titleKeyEnc,tr1,headdata1,masterKeyRev
					if verification2 == True:	
						return True,True,titleKeyEnc,tr2,headdata2,masterKeyRev					
				return False,False,False,False,False,masterKeyRev			
		
	def restorehead_ntr(self):		
		sign1 = self.header.signature1		
		self.header.seek(0x200)	
		headdata = self.header.read(0x200)
		card='01';card=bytes.fromhex(card)
		eshop='00';eshop=bytes.fromhex(eshop)
		#print(hx(headdata))
		#Hex.dump(headdata)				
		pubkey=RSA.RsaKey(n=nca_header_fixed_key_modulus, e=RSA_PUBLIC_EXPONENT)
		rsapss = PKCS1_PSS.new(pubkey)
		digest = SHA256.new(headdata)
		verification=rsapss.verify(digest, sign1)	
		crypto1=self.header.getCryptoType()
		crypto2=self.header.getCryptoType2()	
		if crypto2>crypto1:
			masterKeyRev=crypto2
		if crypto2<=crypto1:	
			masterKeyRev=crypto1	
		if	self.header.getgamecard() == 0:		
			headdata2 = b''
			headdata2=headdata[0x00:0x04]+eshop+headdata[0x05:]		
			digest2 = SHA256.new(headdata2)	
			verification2=rsapss.verify(digest2, sign1)
			if verification2 == True:
				return True,False,False,headdata2,masterKeyRev	
			else:	
				headdata2 = b''
				headdata2=headdata[0x00:0x04]+card+headdata[0x05:]		
				digest2 = SHA256.new(headdata2)	
				verification2=rsapss.verify(digest2, sign1)	
				if verification2 == True:
					return True,False,True,headdata2,masterKeyRev					
		else:
			headdata2 = b''
			headdata2=headdata[0x00:0x04]+eshop+headdata[0x05:]	
			digest2 = SHA256.new(headdata2)
			verification2=rsapss.verify(digest2, sign1)			
			if verification2 == True:
				return True,False,True,headdata2,masterKeyRev	
			else:	
				headdata2 = b''
				headdata2=headdata[0x00:0x04]+card+headdata[0x05:]		
				digest2 = SHA256.new(headdata2)	
				verification2=rsapss.verify(digest2, sign1)	
				if verification2 == True:
					return True,False,False,headdata2,masterKeyRev
				else:
					pass
		if self.header.contentType == Type.Content.META:
			return False,False,False,False,masterKeyRev
		key = Keys.keyAreaKey(Keys.getMasterKeyIndex(masterKeyRev), self.header.keyIndex)				
		crypto = aes128.AESECB(key)
		encKeyBlock = self.header.getKeyBlock()
		decKeyBlock = crypto.decrypt(encKeyBlock)	
		nlist=list()
		for i in range(9):
			nlist.append(i)
		sorted(nlist, key=int, reverse=True)		
		for i in nlist:
			if i<3:
				crypto1='0'+str(i)
				crypto2='00'
			else:
				crypto1='02'
				crypto2='0'+str(i)	
			newMasterKeyRev=i
			key = Keys.keyAreaKey(Keys.getMasterKeyIndex(newMasterKeyRev), self.header.keyIndex)				
			crypto = aes128.AESECB(key)
			reEncKeyBlock = crypto.encrypt(decKeyBlock)				
			crypto1=bytes.fromhex(crypto1);crypto2=bytes.fromhex(crypto2)				
			headdata1 = b''				
			headdata1=headdata[0x00:0x04]+card+headdata[0x05:0x06]+crypto1+headdata[0x07:0x20]+crypto2+headdata[0x21:0x100]+reEncKeyBlock+headdata[0x140:]
			#print(hx(headdata1))
			headdata2 = b''
			headdata2=headdata[0x00:0x04]+eshop+headdata1[0x05:]	
			#print(hx(headdata2))
			if self.header.contentType != Type.Content.META: 
				digest1 = SHA256.new(headdata1)
				digest2 = SHA256.new(headdata2)
				verification1=rsapss.verify(digest1, sign1)		
				verification2=rsapss.verify(digest2, sign1)	
				if verification1 == True:
					if	self.header.getgamecard() == 0:					
						return True,True,True,headdata1,newMasterKeyRev
					else:
						return True,True,False,headdata1,newMasterKeyRev				
				if verification2 == True:
					if	self.header.getgamecard() == 0:					
						return True,True,False,headdata2,newMasterKeyRev	
					else:				
						return True,True,True,headdata2,newMasterKeyRev	       
		return False,False,False,False,masterKeyRev	

#READ NACP FILE WITHOUT EXTRACTION	
	def read_nacp(self,feed=''):
		if 	str(self.header.contentType) == 'Content.CONTROL':
			offset=self.get_nacp_offset()
			for f in self:
				f.seek(offset)
				nacp = Nacp()	
				feed=nacp.par_getNameandPub(f.read(0x300*15),feed)
				message='...............................';print(message);feed+=message+'\n'	
				message='NACP FLAGS';print(message);feed+=message+'\n'						
				message='...............................';print(message);feed+=message+'\n'
				f.seek(offset+0x3000)							
				feed=nacp.par_Isbn(f.read(0x24),feed)		
				f.seek(offset+0x3025)							
				feed=nacp.par_getStartupUserAccount(f.readInt8('little'),feed)	
				feed=nacp.par_getUserAccountSwitchLock(f.readInt8('little'),feed)		
				feed=nacp.par_getAddOnContentRegistrationType(f.readInt8('little'),feed)						
				feed=nacp.par_getContentType(f.readInt8('little'),feed)	
				feed=nacp.par_getParentalControl(f.readInt8('little'),feed)
				feed=nacp.par_getScreenshot(f.readInt8('little'),feed)
				feed=nacp.par_getVideoCapture(f.readInt8('little'),feed)
				feed=nacp.par_dataLossConfirmation(f.readInt8('little'),feed)
				feed=nacp.par_getPlayLogPolicy(f.readInt8('little'),feed)
				feed=nacp.par_getPresenceGroupId(f.readInt64('little'),feed)
				f.seek(offset+0x3040)
				listages=list()
				message='...............................';print(message);feed+=message+'\n'						
				message='Age Ratings';print(message);feed+=message+'\n'	
				message='...............................';print(message);feed+=message+'\n'						
				for i in range(12):
					feed=nacp.par_getRatingAge(f.readInt8('little'),i,feed)
				f.seek(offset+0x3060)		
				message='...............................';print(message);feed+=message+'\n'						
				message='NACP ATTRIBUTES';print(message);feed+=message+'\n'	
				message='...............................';print(message);feed+=message+'\n'
				try:
					feed=nacp.par_getDisplayVersion(f.read(0xF),feed)		
					f.seek(offset+0x3070)							
					feed=nacp.par_getAddOnContentBaseId(f.readInt64('little'),feed)
					f.seek(offset+0x3078)							
					feed=nacp.par_getSaveDataOwnerId(f.readInt64('little'),feed)
					f.seek(offset+0x3080)							
					feed=nacp.par_getUserAccountSaveDataSize(f.readInt64('little'),feed)	
					f.seek(offset+0x3088)								
					feed=nacp.par_getUserAccountSaveDataJournalSize(f.readInt64('little'),feed)	
					f.seek(offset+0x3090)	
					feed=nacp.par_getDeviceSaveDataSize(f.readInt64('little'),feed)	
					f.seek(offset+0x3098)	
					feed=nacp.par_getDeviceSaveDataJournalSize(f.readInt64('little'),feed)	
					f.seek(offset+0x30A0)	
					feed=nacp.par_getBcatDeliveryCacheStorageSize(f.readInt64('little'),feed)		
					f.seek(offset+0x30A8)	
					feed=nacp.par_getApplicationErrorCodeCategory(f.read(0x07),feed)	
					f.seek(offset+0x30B0)
					feed=nacp.par_getLocalCommunicationId(f.readInt64('little'),feed)	
					f.seek(offset+0x30F0)
					feed=nacp.par_getLogoType(f.readInt8('little'),feed)							
					feed=nacp.par_getLogoHandling(f.readInt8('little'),feed)		
					feed=nacp.par_getRuntimeAddOnContentInstall(f.readInt8('little'),feed)	
					feed=nacp.par_getCrashReport(f.readInt8('little'),feed)	
					feed=nacp.par_getHdcp(f.readInt8('little'),feed)		
					feed=nacp.par_getSeedForPseudoDeviceId(f.readInt64('little'),feed)	
					f.seek(offset+0x3100)			
					feed=nacp.par_getBcatPassphrase(f.read(0x40),feed)	
					f.seek(offset+0x3148)			
					feed=nacp.par_UserAccountSaveDataSizeMax(f.readInt64('little'),feed)						
					f.seek(offset+0x3150)			
					feed=nacp.par_UserAccountSaveDataJournalSizeMax(f.readInt64('little'),feed)
					f.seek(offset+0x3158)			
					feed=nacp.par_getDeviceSaveDataSizeMax(f.readInt64('little'),feed)
					f.seek(offset+0x3160)			
					feed=nacp.par_getDeviceSaveDataJournalSizeMax(f.readInt64('little'),feed)							
					f.seek(offset+0x3168)			
					feed=nacp.par_getTemporaryStorageSize(f.readInt64('little'),feed)		
					feed=nacp.par_getCacheStorageSize(f.readInt64('little'),feed)			
					f.seek(offset+0x3178)		
					feed=nacp.par_getCacheStorageJournalSize(f.readInt64('little'),feed)							
					feed=nacp.par_getCacheStorageDataAndJournalSizeMax(f.readInt64('little'),feed)		
					f.seek(offset+0x3188)	
					feed=nacp.par_getCacheStorageIndexMax(f.readInt64('little'),feed)		
					feed=nacp.par_getPlayLogQueryableApplicationId(f.readInt64('little'),feed)		
					f.seek(offset+0x3210)	
					feed=nacp.par_getPlayLogQueryCapability(f.readInt8('little'),feed)	
					feed=nacp.par_getRepair(f.readInt8('little'),feed)	
					feed=nacp.par_getProgramIndex(f.readInt8('little'),feed)	
					feed=nacp.par_getRequiredNetworkServiceLicenseOnLaunch(f.readInt8('little'),feed)	
				except:continue	
		return feed				

#PATCH NETWORK LICENSE
	def patch_netlicense(self):
		if 	str(self.header.contentType) == 'Content.CONTROL':
			offset=self.get_nacp_offset()
			for f in self:
				nacp = Nacp()
				print('CURRENT VALUES:')
				f.seek(offset+0x3025)				
				startup_acc=f.readInt8('little')
				netlicense=f.readInt8('little')				
				f.seek(offset+0x3213)
				netlicense=f.readInt8('little')	
				nacp.par_getStartupUserAccount(startup_acc)					
				nacp.par_getRequiredNetworkServiceLicenseOnLaunch(netlicense)	
				if netlicense==0 and startup_acc<2:
					print(str(self._path)+" doesn't need a linked account")
					return False
				else:
					print('  -> '+str(self._path)+" needs a linked account. Patching...")
					print('NEW VALUES:')
					if startup_acc==2:
						f.seek(offset+0x3025)	
						f.writeInt8(1)
					if netlicense==1:						
						f.seek(offset+0x3213)
						f.writeInt8(0)
					f.seek(offset+0x3025)	
					nacp.par_getStartupUserAccount(f.readInt8('little'))
					f.seek(offset+0x3213)
					nacp.par_getRequiredNetworkServiceLicenseOnLaunch(f.readInt8('little'))		
					return True
	def redo_lvhashes(self):
		if 	str(self.header.contentType) == 'Content.CONTROL':
			#offset=self.get_nacp_offset()
			for fs in self.sectionFilesystems:
				pfs0=fs
				sectionHeaderBlock = fs.buffer
				inmemoryfile = io.BytesIO(sectionHeaderBlock)
				self.seek(fs.offset)
				pfs0Offset=fs.offset
				leveldata,hash,masterhashsize,superhashoffset=self.prIVFCData(inmemoryfile)
				return leveldata,superhashoffset
				
	def set_lv_hash(self,j,leveldata):
		if 	str(self.header.contentType) == 'Content.CONTROL':
			for fs in self.sectionFilesystems:
				levelnumb=leveldata[j][0]
				lvoffs=leveldata[j][1]
				levelsize=leveldata[j][2]
				lvbsize=leveldata[j][3]
				fs.seek(lvoffs)
				data = fs.read(lvbsize)
				newhash=(str(sha256(data).hexdigest()))
				fs.seek((j-1)*0x4000)
				hashlv=(hx(fs.read(32))).decode('utf-8')
				if str(hashlv) != str(newhash):
					fs.seek((j-1)*0x4000)
					sha=bytes.fromhex(newhash)
					fs.write(sha)	
					print('Old lv'+str(j)+' hash: '+str(hashlv))
					print('New lv'+str(j)+' hash: '+str(newhash))

	def set_lvsuperhash(self,leveldata,superhashoffset):
		if 	str(self.header.contentType) == 'Content.CONTROL':
			for fs in self.sectionFilesystems:
				memlv0 = io.BytesIO(fs.read((leveldata[0][2])*(len(leveldata)-1)))
				memlv0.seek(0);newlvdata=memlv0.read()				
				memlv0.seek(0);ndat=memlv0.read(0x4000)
				superhash=(str(sha256(ndat).hexdigest()))
				self.header.seek(0x400+superhashoffset)
				test = hx((self.header.read(32))).decode('utf-8');print('-OLD IVFC_Hash: '+str(test))
				self.header.seek(0x400+superhashoffset)
				self.header.write(bytes.fromhex(superhash))
				self.header.seek(0x400+superhashoffset)
				newivfchash = hx((self.header.read(32))).decode('utf-8');print('-NEW IVFC_Hash: '+str(newivfchash))
				fs.seek(0)
				fs.write(newlvdata)						
				
	def prIVFCData(self,inmemoryfile):
		#Hex.dump(inmemoryfile.read())
		inmemoryfile.seek(0)
		version=int.from_bytes(inmemoryfile.read(0x2), byteorder='little', signed=True);print('-Version: '+str(version))
		fstype=int.from_bytes(inmemoryfile.read(0x1), byteorder='little', signed=True);print('-FileSystemtype: '+str(fstype))		
		hashtype=int.from_bytes(inmemoryfile.read(0x1), byteorder='little', signed=True);print('-HashType: '+str(hashtype))
		enctype=int.from_bytes(inmemoryfile.read(0x1), byteorder='little', signed=True);print('-EncType: '+str(enctype))	
		nulldata=inmemoryfile.read(0x3)
		magic=inmemoryfile.read(0x4);print('-Magic: '+str(magic))
		magicnumber=int.from_bytes(inmemoryfile.read(0x4), byteorder='little', signed=True);print('-MagicNumber: '+str(magicnumber))			
		masterhashsize=int.from_bytes(inmemoryfile.read(0x4), byteorder='little', signed=True)*0x200;print('-MasterHashSize: '+str(masterhashsize))			
		numberLevels=int.from_bytes(inmemoryfile.read(0x4), byteorder='little', signed=True);print('-Number: '+str(numberLevels))			
		leveldata=list();c=24
		for i in range(numberLevels-1):
			lvoffs=int.from_bytes(inmemoryfile.read(0x8), byteorder='little', signed=True);print('-level'+str(i)+' offs: '+str(lvoffs))			
			lvsize=int.from_bytes(inmemoryfile.read(0x8), byteorder='little', signed=True);print('-level'+str(i)+' size: '+str(lvsize))			
			lvbsize=2**int.from_bytes(inmemoryfile.read(0x4), byteorder='little', signed=True);print('-level'+str(i)+' block size: '+str(lvbsize))			
			treserved=int.from_bytes(inmemoryfile.read(0x4), byteorder='little', signed=True);print('-level'+str(i)+' Reserved: '+str(treserved))			
			leveldata.append([i,lvoffs,lvsize,lvbsize])
			c=c+24	
		inmemoryfile.read(32);c=c+32
		hash = hx((inmemoryfile.read(32))).decode('utf-8');print('-IVFC_Hash: '+str(hash))
		return leveldata,hash,masterhashsize,c

	def pr_ivfcsuperhash(self, file = None, mode = 'rb'):					
		crypto1=self.header.getCryptoType()	
		crypto2=self.header.getCryptoType2()		
		if crypto1 == 2:
			if crypto1 > crypto2:								
				masterKeyRev=crypto1
			else:			
				masterKeyRev=crypto2
		else:			
			masterKeyRev=crypto2	
		decKey = Keys.decryptTitleKey(self.header.titleKeyDec, Keys.getMasterKeyIndex(masterKeyRev))
		for f in self.sectionFilesystems:
			#print(f.fsType);print(f.cryptoType)
			if f.fsType == Type.Fs.ROMFS and f.cryptoType == Type.Crypto.CTR:	
				ncaHeader = NcaHeader()
				self.header.rewind()
				ncaHeader = self.header.read(0x400)
				#Hex.dump(ncaHeader)
				pfs0=f
				#Hex.dump(pfs0.read())
				sectionHeaderBlock = f.buffer

				levelOffset = int.from_bytes(sectionHeaderBlock[0x18:0x20], byteorder='little', signed=False)
				levelSize = int.from_bytes(sectionHeaderBlock[0x20:0x28], byteorder='little', signed=False)

				pfs0Header = pfs0.read(levelSize)
				if sectionHeaderBlock[8:12] == b'IVFC':	
					data = pfs0Header;
					Hex.dump(pfs0Header)
					print(str('1: ')+hx(sectionHeaderBlock[0xc8:0xc8+0x20]).decode('utf-8'))
					print(str('2: ')+str(sha256(data).hexdigest()))
					superhash=str(sha256(data).hexdigest())
					return superhash
						

	def verify_hash_nca(self,buffer,origheader,didverify,feed):
		verdict=True; basename=str(os.path.basename(os.path.abspath(self._path)))			
		if feed == False:
			feed=''				
		message='***************';print(message);feed+=message+'\n'
		message=('HASH TEST');print(message);feed+=message+'\n'
		message='***************';print(message);feed+=message+'\n'			
		
		message=(str(self.header.titleId)+' - '+str(self.header.contentType));print(message);feed+=message+'\n'
		ncasize=self.header.size						
		t = tqdm(total=ncasize, unit='B', unit_scale=True, leave=False)	
		i=0		
		self.rewind();
		rawheader=self.read(0xC00)
		self.rewind()												
		for data in iter(lambda: self.read(int(buffer)), ""):				
			if i==0:	
				sha=sha256()
				self.seek(0xC00)
				sha.update(rawheader)
				if origheader != False:
					sha0=sha256()
					sha0.update(origheader)	
				i+=1
				t.update(len(data))
				self.flush()
			else:		
				sha.update(data)
				if origheader != False:
					sha0.update(data)								
				t.update(len(data))
				self.flush()
				if not data:				
					break						
		t.close()	
		sha=sha.hexdigest()	
		if origheader != False:
			sha0=sha0.hexdigest()				
		message=('  - File name: '+basename);print(message);feed+=message+'\n'
		message=('  - SHA256: '+sha);print(message);feed+=message+'\n'
		if origheader != False:
			message=('  - ORIG_SHA256: '+sha0);print(message);feed+=message+'\n'						
		if str(basename)[:16] == str(sha)[:16]:
			message=('   > FILE IS CORRECT');print(message);feed+=message+'\n'
		elif origheader != False:
			if str(basename)[:16] == str(sha0)[:16]:		
				message=('   > FILE IS CORRECT');print(message);feed+=message+'\n'
			else:
				message=('   > FILE IS CORRUPT');print(message);feed+=message+'\n'
				verdict = False	
		elif  self.header.contentType == Type.Content.META and didverify == True:		
			message=('   > RSV WAS CHANGED');print(message);feed+=message+'\n'
			#print('   > CHECKING INTERNAL HASHES')								
			message=('     * FILE IS CORRECT');print(message);feed+=message+'\n'							
		else:
			message=('   > FILE IS CORRUPT');print(message);feed+=message+'\n'
			verdict = False
		message=('');print(message);feed+=message+'\n'			
		if verdict == False:
			message=("VERDICT: NCA FILE IS CORRUPT");print(message);feed+=message+'\n'
		if verdict == True:	
			message=('VERDICT: NCA FILE IS CORRECT');print(message);feed+=message+'\n'
		return 	verdict,feed					