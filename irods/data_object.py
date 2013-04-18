from os import O_RDONLY, O_WRONLY, O_RDWR
from os.path import basename, dirname

from models import DataObject
from meta import iRODSMetaCollection
from exception import CAT_NO_ACCESS_PERMISSION
from resource_manager import ResourceManager
from message import (iRODSMessage, FileReadRequest, FileWriteRequest, 
    FileSeekRequest, FileSeekResponse, FileOpenRequest, FileCloseRequest, 
    StringStringMap)
from exception import DataObjectDoesNotExist, CollectionDoesNotExist
from api_number import api_number
SEEK_SET = 0
SEEK_CUR = 1
SEEK_END = 2

class iRODSDataObject(object):
    def __init__(self, manager, parent=None, result=None):
        self.manager = manager
        if parent and result:
            self.collection = parent
            for attr in ['id', 'name', 'size', 'checksum', 'create_time', 
                'modify_time']:
                setattr(self, attr, result[getattr(DataObject, attr)])
            self.path = self.collection.path + '/' + self.name
        self._meta = None

    def __repr__(self):
        return "<iRODSDataObject %d %s>" % (self.id, self.name)

    @property
    def metadata(self):
        if not self._meta:
            self._meta = iRODSMetaCollection(self.manager.sess.metadata, DataObject, self.path)
        return self._meta

    def open(self, mode='r'):
        flag, create_if_not_exists, seek_to_end = {
            'r': (O_RDONLY, False, False),
            'r+': (O_RDWR, False, False),
            'w': (O_WRONLY, True, False),
            'w+': (O_RDWR, True, False),
            'a': (O_WRONLY, True, True),
            'a+': (O_RDWR, True, True),
        }[mode]
        conn, desc = self.manager.open_file(self.path, flag)
        return iRODSDataObjectFile(conn, desc)

class iRODSDataObjectFile(object):
    def __init__(self, conn, descriptor):
        self.conn = conn
        self.desc = descriptor
        self.position = 0

    def tell(self):
        return self.position

    def close(self):
        try:
            self.conn.close_file(self.desc)
        except CAT_NO_ACCESS_PERMISSION:
            pass 
        finally:
            self.conn.release()
        return None

    def read(self, size=None):
        if not size:
            return "".join(self.read_gen()())
        contents = self.conn.read_file(self.desc, size)
        if contents:
            self.position += len(contents)
        return contents

    def read_gen(self, chunk_size=4096, close=False):
        def make_gen():
            while True:
                contents = self.read(chunk_size) 
                if not contents:
                    break
                yield contents
            if close:
                self.close()
        return make_gen

    def write(self, string):
        written = self.conn.write_file(self.desc, string)
        self.position += written
        return None

    def seek(self, offset, whence=0):
        pos = self.conn.seek_file(self.desc, offset, whence)
        self.position = pos
        pass

    def __iter__(self):
        reader = self.read_gen()
        chars = []
        for chunk in reader():
            for char in chunk:
                if char == '\n':
                    yield "".join(chars)
                    chars = []
                else:
                    chars.append(char)

    def readline(self):
        pass

    def readlines(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

class DataObjectManager(ResourceManager):
    def get_data_object(self, path):
        try:
            parent = self.sess.collections.get_collection(dirname(path))
        except CollectionDoesNotExist:
            raise DataObjectDoesNotExist()

        results = self.sess.query(DataObject)\
            .filter(DataObject.name == basename(path))\
            .filter(DataObject.collection_id == parent.id)\
            .all()
        # reimplement with .one()
        if results.length == 1:
            return iRODSDataObject(self, parent, results[0])
        else:
            raise DataObjectDoesNotExist()

    def create_data_object(self, path):
        message_body = FileOpenRequest(
            objPath=path,
            createMode=0644,
            openFlags=0,
            offset=0,
            dataSize=-1,
            numThreads=0,
            oprType=0,
            KeyValPair_PI=StringStringMap({'dataType': 'generic'}),
        )
        message = iRODSMessage('RODS_API_REQ', msg=message_body,
            int_info=api_number['DATA_OBJ_CREATE_AN'])

        with self.sess.pool.get_connection() as conn:
            conn.send(message)
            response = conn.recv()
            desc = response.int_info
            conn.close_file(desc)

        return self.get_data_object(path)

    def open_file(self, path, mode):
        message_body = FileOpenRequest(
            objPath=path,
            createMode=0,
            openFlags=mode,
            offset=0,
            dataSize=-1,
            numThreads=0,
            oprType=0,
            KeyValPair_PI=StringStringMap(),
        )
        message = iRODSMessage('RODS_API_REQ', msg=message_body, 
            int_info=api_number['DATA_OBJ_OPEN_AN'])

        conn = self.sess.pool.get_connection()
        conn.send(message)
        response = conn.recv()
        return (conn, response.int_info)

    def unlink_data_object(self, path):
        message_body = FileOpenRequest(
            objPath=path,
            createMode=0,
            openFlags=0,
            offset=0,
            dataSize=-1,
            numThreads=0,
            oprType=0,
            KeyValPair_PI=StringStringMap(),
        )
        message = iRODSMessage('RODS_API_REQ', msg=message_body,
            int_info=api_number['DATA_OBJ_UNLINK_AN'])

        with self.sess.pool.get_connection() as conn:
            conn.send(message)
            response = conn.recv()

    def move_file(self, path):
        pass
