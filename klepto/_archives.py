#!/usr/bin/env python
#
# Author: Mike McKerns (mmckerns @caltech and @uqfoundation)
# Copyright (c) 2013-2015 California Institute of Technology.
# License: 3-clause BSD.  The full license text is available at:
#  - http://trac.mystic.cacr.caltech.edu/project/pathos/browser/klepto/LICENSE
"""
custom caching dict, which archives results to memory, file, or database
"""
from __future__ import absolute_import
import os
import sys
import shutil
from random import random
from pickle import PROTO, STOP
try:
  from collections import KeysView, ValuesView, ItemsView
  _view = getattr(dict, 'viewkeys', False)
  _view = True if _view else False # True if 2.7
except ImportError:
  _view = False
try:
  from sqlalchemy import create_engine, delete, select, Column, MetaData, Table
  from sqlalchemy.types import PickleType, String, Text#, BLOB
  __alchemy = True
except ImportError:
  __alchemy = False
import dill
from dill.source import getimportable
from pox import mkdir, rmtree, walk
from .crypto import hash
from . import _pickle

__all__ = ['cache','dict_archive','null_archive','dir_archive',\
           'file_archive','sql_archive','sqltable_archive']

PREFIX = "K_"  # hash needs to be importable
TEMP = "I_"    # indicates 'temporary' file
#DEAD = "D_"    # indicates 'deleted' key


class cache(dict):
    """dictionary augmented with an archive backend"""
    def __init__(self, *args, **kwds):
        """initialize a dictionary with an archive backend

    Additional Inputs:
        archive: instance of archive object
        """
        self.__swap__ = null_archive()
        self.__archive__ = kwds.pop('archive', null_archive())
        dict.__init__(self, *args, **kwds)
       #self.__state__ = {}
        return
    def __repr__(self):
        archive = self.archive.__class__.__name__
        name = self.archive.name
        if name:
            return "%s(%r, %s, cached=True)" % (archive, str(name), dict(self))
        return "%s(%s, cached=True)" % (archive, dict(self))
    __repr__.__doc__ = dict.__repr__.__doc__
    def load(self, *args): #FIXME: archive may use key 'encoding' (dir_archive)
        """load archive contents

    If arguments are given, only load the specified keys
        """
        if not args:
            self.update(self.archive.__asdict__())
        for arg in args:
            try:
                self.update({arg:self.archive[arg]})
            except KeyError:
                pass
        return
    def dump(self, *args): #FIXME: archive may use key 'encoding' (dir_archive)
        """dump contents to archive

    If arguments are given, only dump the specified keys
        """
        if not args:
            self.archive.update(self)
        for arg in args:
            if arg in self:
                self.archive.update({arg:self.__getitem__(arg)})
        return
    def archived(self, *on):
        """check if the cache is archived, or toggle archiving

    If on is True, turn on the archive; if on is False, turn off the archive
        """
        L = len(on)
        if not L: return not isinstance(self.archive, null_archive)
        if L > 1: raise TypeError("archived expected at most 1 argument, got %s" % str(L+1))
        if bool(on[0]):
            if not isinstance(self.__swap__, null_archive):
                self.__swap__, self.__archive__ = self.__archive__, self.__swap__
            elif isinstance(self.__archive__, null_archive):
                raise ValueError("no valid archive has been set")
        else:
            if not isinstance(self.__archive__, null_archive):
                self.__swap__, self.__archive__ = self.__archive__, self.__swap__
    def sync(self, clear=False):
        """synchronize cache and archive contents

    If clear is True, clear all archive contents before synchronizing cache
        """
        if clear: self.archive.clear()
        self.dump()
        if not clear: self.load()
        return
    def drop(self): #XXX: sync first?
        "set the current archive to NULL"
        self.archived(True) #XXX: should not throw error if not archived?
        self.archive = null_archive()
        return
    def open(self, archive):
        "replace the current archive with the archive provided"
        try: self.archived(True)
        except ValueError: pass
        self.archive = archive
        return
    def __get_archive(self):
       #if not isinstance(self.__archive__, null_archive):
       #    return
        return self.__archive__
    def __archive(self, archive):
        if not isinstance(self.__swap__, null_archive):
            self.__swap__, self.__archive__ = self.__archive__, self.__swap__
        self.__archive__ = archive
    # interface
    archive = property(__get_archive, __archive)
    pass


class dict_archive(dict):
    """dictionary with an archive interface"""
    def __init__(self, *args, **kwds):
        """initialize a dictionary archive"""
        name = kwds.pop('__magic_key_0192837465__', None)
        dict.__init__(self, *args, **kwds)
        self.__state__ = {
            'id': name # can be used to store a 'name'
        }
        return
    def __asdict__(self):
        """build a dictionary containing the archive contents"""
        return self.copy()
    def __repr__(self):
        return "dict_archive(%s, cached=False)" % (self.__asdict__())
    __repr__.__doc__ = dict.__repr__.__doc__
    # interface
    def load(self, *args):
        """does nothing. required to use an archive as a cache"""
        return
    dump = load
    def archived(self, *on):
        """check if the cache is a persistent archive"""
        L = len(on)
        if not L: return False
        if L > 1: raise TypeError("archived expected at most 1 argument, got %s" % str(L+1))
        raise ValueError("cannot toggle archive")
    def sync(self, clear=False):
        "does nothing. required to use an archive as a cache"
        pass
    def drop(self): #XXX: or actually drop the backend?
        "set the current archive to NULL"
        return self.__archive(None)
    def open(self, archive):
        "replace the current archive with the archive provided"
        return self.__archive(archive)
    def __get_archive(self):
        return self
    def __get_name(self):
        return self.__state__['id']
    def __archive(self, archive):
        raise ValueError("cannot set new archive")
    archive = property(__get_archive, __archive)
    name = property(__get_name, __archive)
    pass


class null_archive(dict):
    """dictionary interface to nothing -- it's always empty"""
    def __init__(self, *args, **kwds):
        """initialize a permanently-empty dictionary"""
        name = kwds.pop('__magic_key_0192837465__', None)
        dict.__init__(self)
        self.__state__ = {
            'id': name # can be used to store a 'name'
        }
        return
    def __asdict__(self):
        """build a dictionary containing the archive contents"""
        return self
    def __setitem__(self, key, value):
        pass
    __setitem__.__doc__ = dict.__setitem__.__doc__
    def update(self, adict, **kwds):
        pass
    update.__doc__ = dict.update.__doc__
    def setdefault(self, key, *value):
        return self.get(key, *value)
    setdefault.__doc__ = dict.setdefault.__doc__
    def __repr__(self):
        return "null_archive(cached=False)"
    __repr__.__doc__ = dict.__repr__.__doc__
    # interface
    def load(self, *args):
        """does nothing. required to use an archive as a cache"""
        return
    dump = load
    def archived(self, *on):
        """check if the cache is a persistent archive"""
        L = len(on)
        if not L: return False
        if L > 1: raise TypeError("archived expected at most 1 argument, got %s" % str(L+1))
        raise ValueError("cannot toggle archive")
    def sync(self, clear=False):
        "does nothing. required to use an archive as a cache"
        pass
    def drop(self): #XXX: or actually drop the backend?
        "set the current archive to NULL"
        return self.__archive(None)
    def open(self, archive):
        "replace the current archive with the archive provided"
        return self.__archive(archive)
    def __get_archive(self):
        return self
    def __get_name(self):
        return self.__state__['id']
    def __archive(self, archive):
        raise ValueError("cannot set new archive")
    archive = property(__get_archive, __archive)
    name = property(__get_name, __archive)
    pass


class dir_archive(dict):
    """dictionary-style interface to a folder of files"""
    def __init__(self, dirname=None, serialized=True, compression=0, permissions=None, **kwds):
        """initialize a file folder with a synchronized dictionary interface

    Inputs:
        dirname: name of the root archive directory [default: memo]
        serialized: if True, pickle file contents; otherwise save python objects
        compression: compression level (0 to 9) [default: 0 (no compression)]
        permissions: octal representing read/write permissions [default: 0o775]
        memmode: access mode for files, one of {None, 'r+', 'r', 'w+', 'c'}
        memsize: approximate size (in MB) of cache for in-memory compression
        """
        #XXX: if compression or mode is given, use joblib-style pickling
        #     (ignoring 'serialized'); else if serialized, use dill unless
        #     fast=True (then use joblib-style pickling). If not serialized,
        #     then write raw objects and load objects with import.
        """dirname = full filepath"""
        if dirname is None: #FIXME: default root as /tmp or something better
            dirname = 'memo' #FIXME: need better default
        # set state
        self.__state__ = {
            # undocumented: True=joblib-style, False=dill-style pickling
            'fast': kwds.get('fast', False),
            # settings
            'serialized': serialized,
            'compression': compression,
            'permissions': permissions,
            'memmode': kwds.get('memmode', None),
            'memsize': kwds.get('memsize', 100), # unused?
            'root': dirname
        }
        # if not serialized, then set fast=False
        if not serialized:
            self.__state__['compression'] = 0
            self.__state__['memmode'] = None
            self.__state__['fast'] = False
        # if compression or mode, then set fast=True
        elif compression or self.__state__['memmode']:
            self.__state__['fast'] = True
        # ELSE: use dill if fast=False, else use _pickle
        try:
            self.__state__['root'] = mkdir(dirname, mode=self.__state__['permissions'])
        except OSError: # then directory already exists
            self.__state__['root'] = os.path.abspath(dirname)
        return
    def __reduce__(self):
        dirname = self.name
        serial = self.__state__['serialized']
        compress = self.__state__['compression']
        perm = self.__state__['permissions']
        state = {'__state__': self.__state__}
        return (self.__class__, (dirname, serial, compress, perm), state)
    def __asdict__(self):
        """build a dictionary containing the archive contents"""
        # get the names of all directories in the directory
        keys = self._keydict()
        # get the values
        return dict((key,self.__getitem__(key)) for key in keys)
    #FIXME: missing __cmp__, __...__
    def __eq__(self, y):
        try:
            if y.__module__ != self.__module__: return NotImplemented
            return self.__asdict__() == y.__asdict__() #XXX: faster than get?
           #if len(self) != len(y): return False
           #try: s = min(k for k in self if self.get(k) != y.get(k))
           #except ValueError: s = []
           #try: v = min(k for k in y if y.get(k) != self.get(k))
           #except ValueError: v = []
           #if s != v: return False
           #elif s == []: return True
           #return self[s] == y[v]
        except: return NotImplemented
    __eq__.__doc__ = dict.__eq__.__doc__
    def __ne__(self, y):
        y = self.__eq__(y)
        return NotImplemented if y is NotImplemented else not y
    __ne__.__doc__ = dict.__ne__.__doc__
    def __delitem__(self, key):
        try:
            memo = {key: None}
            self._rmdir(key)
        except:
            memo = {}
        memo.__delitem__(key)
        return
    __delitem__.__doc__ = dict.__delitem__.__doc__
    def __getitem__(self, key):
        return self._lookup(key)
    __getitem__.__doc__ = dict.__getitem__.__doc__
    def __repr__(self):
        return "dir_archive('%s', %s, cached=False)" % (self.name, self.__asdict__())
    __repr__.__doc__ = dict.__repr__.__doc__
    def __setitem__(self, key, value):
        self._store(key, value, input=False) # input=True also stores input
        return
    __setitem__.__doc__ = dict.__setitem__.__doc__
    def clear(self):
        rmtree(self.__state__['root'], self=False, ignore_errors=True)
        return
    clear.__doc__ = dict.clear.__doc__
    def copy(self, name=None): #XXX: always None? or allow other settings?
        "D.copy(name) -> a copy of D, with a new archive at the given name"
        if name is None:
            name = self.__state__['root']
        else: #XXX: overwrite?
            shutil.copytree(self.__state__['root'], os.path.abspath(name))
        adict = dir_archive(dirname=name, **self.__state__)
       #adict.update(self.__asdict__())
        return adict
    def fromkeys(self, *args): #XXX: build a dict (not an archive)?
        return dict.fromkeys(*args)
    fromkeys.__doc__ = dict.fromkeys.__doc__
    def get(self, key, value=None):
        try:
            return self.__getitem__(key)
        except:
            return value
    get.__doc__ = dict.get.__doc__
    def __contains__(self, key):
        _dir = self._getdir(key)
        return os.path.exists(_dir)
    __contains__.__doc__ = dict.__contains__.__doc__
    if getattr(dict, 'has_key', None):
        has_key = __contains__
        has_key.__doc__ = dict.has_key.__doc__
        def __iter__(self):
            return self._keydict().iterkeys()
        def iteritems(self): #XXX: should be dictionary-itemiterator
            keys = self._keydict()
            return ((key,self.__getitem__(key)) for key in keys)
        iteritems.__doc__ = dict.iteritems.__doc__
        iterkeys = __iter__
        iterkeys.__doc__ = dict.iterkeys.__doc__
        def itervalues(self): #XXX: should be dictionary-valueiterator
            keys = self._keydict()
            return (self.__getitem__(key) for key in keys)
        itervalues.__doc__ = dict.itervalues.__doc__
    else:
        def __iter__(self):
            return iter(self._keydict().keys())
    __iter__.__doc__ = dict.__iter__.__doc__
    def keys(self):
        if sys.version_info[0] < 3:
            return self._keydict().keys()
        else: return KeysView(self) #XXX: show keys not dict
    keys.__doc__ = dict.keys.__doc__
    def items(self):
        if sys.version_info[0] < 3:
            keys = self._keydict()
            return [(key,self.__getitem__(key)) for key in keys]
        else: return ItemsView(self) #XXX: show items not dict
    items.__doc__ = dict.items.__doc__
    def values(self):
        if sys.version_info[0] < 3:
            keys = self._keydict()
            return [self.__getitem__(key) for key in keys]
        else: return ValuesView(self) #XXX: show values not dict
    values.__doc__ = dict.values.__doc__
    if _view:
        def viewkeys(self):
            return KeysView(self) #XXX: show keys not dict
        viewkeys.__doc__ = dict.viewkeys.__doc__
        def viewvalues(self):
            return ValuesView(self) #XXX: show values not dict
        viewvalues.__doc__ = dict.viewvalues.__doc__
        def viewitems(self):
            return ItemsView(self) #XXX: show items not dict
        viewitems.__doc__ = dict.viewitems.__doc__
    def pop(self, key, *value): #XXX: or make DEAD ?
        try:
            memo = {key: self.__getitem__(key)}
            self._rmdir(key)
        except:
            memo = {}
        res = memo.pop(key, *value)
        return res
    pop.__doc__ = dict.pop.__doc__
    def popitem(self):
        key = self.__iter__()
        try: key = key.next()
        except StopIteration: raise KeyError("popitem(): dictionary is empty")
        return (key, self.pop(key))
    popitem.__doc__ = dict.popitem.__doc__
    def setdefault(self, key, *value):
        res = self.get(key, *value)
        self.__setitem__(key, res)
        return res
    setdefault.__doc__ = dict.setdefault.__doc__
    def update(self, adict, **kwds):
        if hasattr(adict,'__asdict__'): adict = adict.__asdict__()
        memo = {}
        memo.update(adict, **kwds) #XXX: could be better ?
        for (key,val) in memo.items():
            self.__setitem__(key,val)
        return
    update.__doc__ = dict.update.__doc__
    def __len__(self):
        return len(self._lsdir())

    def _fname(self, key):
        "generate suitable filename for a given key"
        # special handling for pickles; enable non-strings (however 1=='1')
        try: ispickle = key.startswith(PROTO) and key.endswith(STOP)
        except: ispickle = False
        return hash(key, 'md5') if ispickle else str(key) #XXX: always hash?
       ##XXX: below probably fails on windows, and could be huge... use 'md5'
       #return repr(key)[1:-1] if ispickle else str(key) # or repr?

    def _mkdir(self, key):
        "create results subdirectory corresponding to given key"
        key = self._fname(key)
        try:
            return mkdir(PREFIX+key, root=self.__state__['root'], mode=self.__state__['permissions'])
        except OSError: # then directory already exists
            return self._getdir(key)

    def _getdir(self, key):
        "get results directory name corresponding to given key"
        key = self._fname(key)
        return os.path.join(self.__state__['root'], PREFIX+key)

    def _rmdir(self, key):
        "remove results subdirectory corresponding to given key"
        rmtree(self._getdir(key), self=True, ignore_errors=True)
        return
    def _lsdir(self):
        "get a list of subdirectories in the root directory"
        return walk(self.__state__['root'],patterns=PREFIX+'*',recurse=False,folders=True,files=False,links=False)
    def _hasinput(self, root):
        "check if results subdirectory has stored input file"
        return bool(walk(root,patterns=self._args,recurse=False,folders=False,files=True,links=False))
    def _getkey(self, root):
        "get key given a results subdirectory name"
        key = os.path.basename(root)[2:]
        return self._lookup(key,input=True) if self._hasinput(root) else key
    def _keydict(self):
        "get a dict of subdirectories in the root directory, with dummy values"
        keys = self._lsdir()
        return dict((self._getkey(key),None) for key in keys)

    def _reverse_lookup(self, args): #XXX: guaranteed 1-to-1 mapping?
        "get subdirectory name from args"
        d = {}
        for key in iter(self._keydict()):
            try:
                if args == self._lookup(key, input=True):
                    d[args] = None #XXX: unnecessarily memory intensive?
                    break
            except KeyError:
                continue
        # throw KeyError(args) if key not found
        del d[args]
        return key
    def _lookup(self, key, input=False):
        "get input or output from subdirectory name"
        _dir = self._getdir(key)
        if self.__state__['serialized']:
            _file = self._args if input else self._file
            _file = os.path.join(_dir, _file)
            try:
                if self.__state__['fast']: #XXX: enable override of 'mode' ?
                    memo = _pickle.load(_file, mmap_mode=self.__state__['memmode'])
                else:
                    f = open(_file, 'rb')
                    memo = dill.load(f)
                    f.close()
            except: #XXX: should only catch the appropriate exceptions
                memo = None
                raise KeyError(key)
               #raise OSError("error reading directory for '%s'" % key)
        else:
            import tempfile
            base = os.path.basename(_dir) #XXX: PREFIX+key
            root = os.path.realpath(self.__state__['root'])
            name = tempfile.mktemp(prefix="_____", dir="").replace("-","_")
            _arg = ".__args__" if input else ""
            string = "from %s%s import memo as %s; sys.modules.pop('%s')" % (base, _arg, name, base)
            try:
                sys.path.insert(0, root)
                exec(string, globals()) #FIXME: unsafe, potential name conflict
                memo = globals().get(name)# None) #XXX: error if not found?
                globals().pop(name, None)
            except: #XXX: should only catch the appropriate exceptions
                raise KeyError(key)
               #raise OSError("error reading directory for '%s'" % key)
            finally:
                sys.path.remove(root)
        return memo
    def _store(self, key, value, input=False):
        "store output (and possibly input) in a subdirectory"
        _key = TEMP+hash(random(), 'md5')
        # create an input file when key is not suitable directory name
        if self._fname(key) != key: input=True
        # create a temporary directory, and dump the results
        try:
            _file = os.path.join(self._mkdir(_key), self._file)
            if input: _args = os.path.join(self._getdir(_key), self._args)
            if self.__state__['serialized']:
                if self.__state__['fast']:
                    compression = self.__state__['compression']
                    _pickle.dump(value, _file, compress=compression)
                    if input: _pickle.dump(key, _args, compress=compression)
                else:
                    f = open(_file, 'wb')
                    dill.dump(value, f)  #XXX: byref=True ?
                    f.close()
                    if input:
                        f = open(_args, 'wb')
                        dill.dump(key, f)
                        f.close()
            else: # try to get an import for the object
                try: memo = getimportable(value, alias='memo', byname=False)
                except AttributeError: #XXX: HACKY... get classes by name
                    memo = getimportable(value, alias='memo')
                #XXX: class instances and such fail... abuse pickle here?
                from .tools import _b
                open(_file, 'wb').write(_b(memo))
                if input:
                    try: memo = getimportable(key, alias='memo', byname=False)
                    except AttributeError:
                        memo = getimportable(key, alias='memo')
                    from .tools import _b
                    open(_args, 'wb').write(_b(memo))
        except OSError:
            "failed to populate directory for '%s'" % key
        # move the results to the proper place
        try: #XXX: possible permissions issues here
            self._rmdir(key) #XXX: 'key' must be a suitable dir name
            os.renames(self._getdir(_key), self._getdir(key))
#       except TypeError: #XXX: catch key that isn't converted to safe filename
#           "error in populating directory for '%s'" % key
        except OSError: #XXX: if rename fails, may need cleanup (_rmdir ?)
            "error in populating directory for '%s'" % key

    def _get_args(self):
        if self.__state__['serialized']: return 'input.pkl'
        return '__args__.py'
    def _get_file(self):
        if self.__state__['serialized']: return 'output.pkl'
        return '__init__.py'
    def _set_file(self, file):
        raise NotImplementedError("cannot set attribute '_file'")

    # interface
    def load(self, *args):
        """does nothing. required to use an archive as a cache"""
        return
    dump = load
    def archived(self, *on):
        """check if the cache is a persistent archive"""
        L = len(on)
        if not L: return True
        if L > 1: raise TypeError("archived expected at most 1 argument, got %s" % str(L+1))
        raise ValueError("cannot toggle archive")
    def sync(self, clear=False):
        "does nothing. required to use an archive as a cache"
        pass
    def drop(self): #XXX: or actually drop the backend?
        "set the current archive to NULL"
        return self.__archive(None)
    def open(self, archive):
        "replace the current archive with the archive provided"
        return self.__archive(archive)
    def __get_archive(self):
        return self
    def __get_name(self):
        return os.path.basename(self.__state__['root'])
    def __archive(self, archive):
        raise ValueError("cannot set new archive")
    archive = property(__get_archive, __archive)
    name = property(__get_name, __archive)
    _file = property(_get_file, _set_file)
    _args = property(_get_args, _set_file)
    pass


class file_archive(dict):
    """dictionary-style interface to a file"""
    def __init__(self, filename=None, serialized=True): # False
        """initialize a file with a synchronized dictionary interface

    Inputs:
        serialized: if True, pickle file contents; otherwise save python objects
        filename: name of the file backend [default: memo.pkl or memo.py]
        """
        """filename = full filepath"""
        if filename is None:
            if serialized: filename = 'memo.pkl' #FIXME: need better default
            else: filename = 'memo.py' #FIXME: need better default
        elif not serialized and not filename.endswith(('.py','.pyc','.pyo','.pyd')): filename = filename+'.py'
        # set state
        self.__state__ = {
            'filename': filename,
            'serialized': serialized
        }
        if not os.path.exists(filename):
            self.__save__({})
        return
    def __reduce__(self):
        fname = self.__state__['filename']
        serial = self.__state__['serialized']
       #state = {'__state__': self.__state__}
        return (self.__class__, (fname, serial))#, state)
    def __asdict__(self):
        """build a dictionary containing the archive contents"""
        filename = self.__state__['filename']
        if self.__state__['serialized']:
            try:
                f = open(filename, 'rb')
                memo = dill.load(f)
                f.close()
            except:
                memo = {}
               #raise OSError("error reading file archive %s" % filename)
        else:
            import tempfile
            file = os.path.basename(filename)
            root = os.path.realpath(filename).rstrip(file)[:-1]
            curdir = os.path.realpath(os.curdir)
            if file.endswith(('.py','.pyc','.pyo','.pyd')):
                file = file.rsplit('.',1)[0]
            name = tempfile.mktemp(prefix="_____", dir="").replace("-","_")
            os.chdir(root)
            string = "from %s import memo as %s; sys.modules.pop('%s')" % (file, name, file)
            try:
                exec(string, globals()) #FIXME: unsafe, potential name conflict
                memo = globals().get(name, {}) #XXX: error if not found ?
                globals().pop(name, None)
            except: #XXX: should only catch appropriate exceptions
                memo = {}
               #raise OSError("error reading file archive %s" % filename)
            finally:
                os.chdir(curdir)
        return memo
    def __save__(self, memo=None):
        """create an archive from the given dictionary"""
        if memo == None: return
        filename = self.__state__['filename']
        _filename = TEMP+hash(random(), 'md5')
        # create a temporary file, and dump the results
        try:
            if self.__state__['serialized']:
                f = open(_filename, 'wb')
                dill.dump(memo, f)  #XXX: byref=True ?
                f.close()
            else: #XXX: likely_import for each item in dict... ?
                from .tools import _b
                open(_filename, 'wb').write(_b('memo = %s' % repr(memo)))
        except OSError:
            "failed to populate file for %s" % filename
        # move the results to the proper place
        try:
            os.remove(filename)
        except: pass
        try:
            os.renames(_filename, filename)
        except OSError:
            "error in populating %s" % filename
        return
    #FIXME: missing __cmp__, __...__
    def __eq__(self, y):
        try:
            if y.__module__ != self.__module__: return NotImplemented
            return self.__asdict__() == y.__asdict__() #XXX: faster than get?
        except: return NotImplemented
    __eq__.__doc__ = dict.__eq__.__doc__
    def __ne__(self, y):
        y = self.__eq__(y)
        return NotImplemented if y is NotImplemented else not y
    __ne__.__doc__ = dict.__ne__.__doc__
    def __delitem__(self, key):
        memo = self.__asdict__()
        memo.__delitem__(key)
        self.__save__(memo)
        return
    __delitem__.__doc__ = dict.__delitem__.__doc__
    def __getitem__(self, key):
        memo = self.__asdict__()
        return memo[key]
    __getitem__.__doc__ = dict.__getitem__.__doc__
    def __repr__(self):
        return "file_archive('%s', %s, cached=False)" % (self.name, self.__asdict__())
    __repr__.__doc__ = dict.__repr__.__doc__
    def __setitem__(self, key, value):
        memo = self.__asdict__()
        memo[key] = value
        self.__save__(memo)
        return
    __setitem__.__doc__ = dict.__setitem__.__doc__
    def clear(self):
        self.__save__({})
        return
    clear.__doc__ = dict.clear.__doc__
    def copy(self, name=None): #XXX: always None? or allow other settings?
        "D.copy(name) -> a copy of D, with a new archive at the given name"
        filename = self.__state__['filename']
        if name is None: name = filename
        else: shutil.copy2(filename, name) #XXX: overwrite?
        adict = {'serialized':self.__state__['serialized'], 'filename':name}
        adict = file_archive(**adict)
       #adict.update(self.__asdict__())
        return adict
    def fromkeys(self, *args): #XXX: build a dict (not an archive)?
        return dict.fromkeys(*args)
    fromkeys.__doc__ = dict.fromkeys.__doc__
    def get(self, key, value=None):
        memo = self.__asdict__()
        return memo.get(key, value)
    get.__doc__ = dict.get.__doc__
    def __contains__(self, key):
        return key in self.__asdict__()
    __contains__.__doc__ = dict.__contains__.__doc__
    if getattr(dict, 'has_key', None):
        has_key = __contains__
        has_key.__doc__ = dict.has_key.__doc__
        def __iter__(self):
            return self.__asdict__().iterkeys()
        def iteritems(self):
            return self.__asdict__().iteritems()
        iteritems.__doc__ = dict.iteritems.__doc__
        iterkeys = __iter__
        iterkeys.__doc__ = dict.iterkeys.__doc__
        def itervalues(self):
            return self.__asdict__().itervalues()
        itervalues.__doc__ = dict.itervalues.__doc__
    else:
        def __iter__(self):
            return iter(self.__asdict__().keys())
    __iter__.__doc__ = dict.__iter__.__doc__
    def keys(self):
        if sys.version_info[0] < 3:
            return self.__asdict__().keys()
        else: return KeysView(self) #XXX: show keys not dict
    keys.__doc__ = dict.keys.__doc__
    def items(self):
        if sys.version_info[0] < 3:
            return self.__asdict__().items()
        else: return ItemsView(self) #XXX: show items not dict
    items.__doc__ = dict.items.__doc__
    def values(self):
        if sys.version_info[0] < 3:
            return self.__asdict__().values()
        else: return ValuesView(self) #XXX: show values not dict
    values.__doc__ = dict.values.__doc__
    if _view:
        def viewkeys(self):
            return KeysView(self) #XXX: show keys not dict
        viewkeys.__doc__ = dict.viewkeys.__doc__
        def viewvalues(self):
            return ValuesView(self) #XXX: show values not dict
        viewvalues.__doc__ = dict.viewvalues.__doc__
        def viewitems(self):
            return ItemsView(self) #XXX: show items not dict
        viewitems.__doc__ = dict.viewitems.__doc__
    def pop(self, key, *value):
        memo = self.__asdict__()
        res = memo.pop(key, *value)
        self.__save__(memo)
        return res
    pop.__doc__ = dict.pop.__doc__
    def popitem(self):
        memo = self.__asdict__()
        res = memo.popitem()
        self.__save__(memo)
        return res
    popitem.__doc__ = dict.popitem.__doc__
    def setdefault(self, key, *value):
        res = self.__asdict__().get(key, *value)
        self.__setitem__(key, res)
        return res
    setdefault.__doc__ = dict.setdefault.__doc__
    def update(self, adict, **kwds):
        if hasattr(adict,'__asdict__'): adict = adict.__asdict__()
        memo = self.__asdict__()
        memo.update(adict, **kwds)
        self.__save__(memo)
        return
    update.__doc__ = dict.update.__doc__
    def __len__(self):
        return len(self.__asdict__())
    # interface
    def load(self, *args):
        """does nothing. required to use an archive as a cache"""
        return
    dump = load
    def archived(self, *on):
        """check if the cache is a persistent archive"""
        L = len(on)
        if not L: return True
        if L > 1: raise TypeError("archived expected at most 1 argument, got %s" % str(L+1))
        raise ValueError("cannot toggle archive")
    def sync(self, clear=False):
        "does nothing. required to use an archive as a cache"
        pass
    def drop(self): #XXX: or actually drop the backend?
        "set the current archive to NULL"
        return self.__archive(None)
    def open(self, archive):
        "replace the current archive with the archive provided"
        return self.__archive(archive)
    def __get_archive(self):
        return self
    def __get_name(self):
        return os.path.basename(self.__state__['filename'])
    def __archive(self, archive):
        raise ValueError("cannot set new archive")
    archive = property(__get_archive, __archive)
    name = property(__get_name, __archive)
    pass


def _sqlname(name):
    """parse database name and table name from given name string

    name: a string of the form 'databaseurl?table=tablename'
    """
    key = '?table='
    if name is None: db, table = None, None # name=None
    elif name.startswith((key,'table=')): # name='table=memo'
        db, table = None, name.lstrip('?').lstrip('table').lstrip('=')
    elif name.count('/'): # name='sqlite:///'
        db, table = name.split(key,1) if name.count(key) else (name, None)
    else: db, table = None, name # name='memo'
    return (db, table)


if __alchemy:
  #FIXME: serialized throws RecursionError... but r'\x80' is valid (so is '80')
  #       however, '\x80' and u'\x80' and b'\x80' are not valid (also not 80)
  #       NOTE: if __alchemy == False: 80, u'\x80', and b'\\x80' are also VALID
  class sql_archive(dict):
      """dictionary-style interface to a sql database"""
      def __init__(self, database=None, **kwds):
          """initialize a sql database with a synchronized dictionary interface

      Connect to an existing database, or initialize a new database, at the
      selected database url. For example, to use a sqlite database 'foo.db'
      in the current directory, database='sqlite:///foo.db'.  To use a mysql
      database 'foo' on localhost, database='mysql://user:pass@localhost/foo'.
      For postgresql, use database='postgresql://user:pass@localhost/foo'. 
      When connecting to sqlite, the default database is ':memory:'; otherwise,
      the default database is 'defaultdb'.  Allows keyword options for database
      configuration, such as connection pooling.

      Inputs:
          database: url of the database backend [default: sqlite:///:memory:]
          serialized: if True, pickle table contents; otherwise cast as strings
          """
          # create database, if doesn't exist
          if database is None: database = 'sqlite:///:memory:'
          elif database == 'sqlite:///': database = 'sqlite:///:memory:'
          _database = database
          try:
              url, dbname = database.rsplit('/', 1)
          except ValueError: # only dbname given
              url, dbname = 'sqlite://', database
              _database = "%s/%s" % (url,dbname)
          if url.endswith(":/") or dbname == '': # then no dbname was given
              url = _database
              dbname = 'defaultdb'
              _database = "%s/%s" % (url,dbname)
          # set state
          self.__state__ = {
              'serialized': bool(kwds.pop('serialized', True)),
              'database': _database,
              # preserve other settings (for copy)
              'config': kwds.copy()
          } #XXX: _engine and _metadata (and _key and _val) also __state__ ?
          # get engine
          if dbname == ':memory:':
              self._engine = create_engine(url, **kwds)
          elif _database.startswith('sqlite'):
              self._engine = create_engine(_database, **kwds)
          else:
              self._engine = create_engine(url) #XXX: **kwds ?
              try:
                  conn = self._engine.connect()
                  if _database.startswith('postgres'):
                      conn.connection.connection.set_isolation_level(0)
                  conn.execute("CREATE DATABASE %s;" % dbname)
              except Exception: pass
              finally:
                  if _database.startswith('postgres'):
                      conn.connection.connection.set_isolation_level(1)
              try:
                  self._engine.execute("USE %s;" % dbname)
              except Exception:
                  pass
              self._engine = create_engine(_database, **kwds)
          # table internals
          self._metadata = MetaData()
          self._key = 'Kkeyqwg907' # primary key name
          self._val = 'Kvalmol142' # object storage name
          # discover all tables #FIXME: with matching self._key
          keys = self._keys()
          [self._mktable(key) for key in keys]
         #self._metadata.create_all(self._engine)
          return
      def __drop__(self, **kwds):
          """drop the associated database

      EXPERIMENTAL: For certain database engines, this may not work due
      to permission issues. Caller may need to be connected as a superuser
      and database owner.
          """
          _database = self.__state__['database']
          url, dbname = _database.rsplit('/', 1)
          self._engine = create_engine(url)
          try:
              conn = self._engine.connect()
              if _database.startswith('postgres'):
                  # these two commands require superuser privs
                  conn.execute("update pg_database set datallowconn = 'false' WHERE datname = '%s';" % dbname)
                  conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '%s';" % dbname) # 'pid' used in postgresql >= 9.2
                  conn.connection.connection.set_isolation_level(0)
              conn.execute("DROP DATABASE %s;" % dbname) # must be db owner
              if _database.startswith('postgres'):
                  conn.connection.connection.set_isolation_level(1)
          except Exception:
              dbpath = _database.split('///')[-1]
              if os.path.exists(dbpath): # else fail silently
                  os.remove(dbpath)
          self._metadata = self._engine = None # self.__state__['table']=None
          return
      def __asdict__(self):
          """build a dictionary containing the archive contents"""
          keys = self._keys()
          return dict((key,self.__getitem__(key)) for key in keys)
      #FIXME: missing __cmp__, __...__
      def __eq__(self, y):
          try:
              if y.__module__ != self.__module__: return NotImplemented
              return self.__asdict__() == y.__asdict__() #XXX: faster than get?
          except: return NotImplemented
      __eq__.__doc__ = dict.__eq__.__doc__
      def __ne__(self, y):
          y = self.__eq__(y)
          return NotImplemented if y is NotImplemented else not y
      __ne__.__doc__ = dict.__ne__.__doc__
      def __delitem__(self, key):
          table = self._gettable(key)
          self._metadata.remove(table)
          table.drop(self._engine) #XXX: optionally delete data ?
          return
      __delitem__.__doc__ = dict.__delitem__.__doc__
      def __getitem__(self, key): #XXX: value is table['key','key']; slow?
          table = self._gettable(key)
          query = select([table], table.c[self._key] == self._key) #XXX: slow?
          row = self._engine.execute(query).fetchone()
          if row is None:
              raise RuntimeError("primary key for '%s' not found" % key)
          return row[self._val]
      __getitem__.__doc__ = dict.__getitem__.__doc__
      def __repr__(self):
          return "sql_archive('%s', %s, cached=False)" % (self.name, self.__asdict__())
      __repr__.__doc__ = dict.__repr__.__doc__
      def __setitem__(self, key, value): #XXX: _setkey is part of _mktable
          value = {self._val: value}
          try:
              table = self._gettable(key) # KeyError if table doesn't exist
              query = table.update().where(table.c[self._key] == self._key)
              values = value
          except KeyError:
              table = self._mktable(key)
              query = table.insert()
              values = {self._key: self._key}
              values.update(value)
          self._engine.execute(query.values(**values))
          return
      __setitem__.__doc__ = dict.__setitem__.__doc__
      def clear(self):
         #self._metadata.drop_all()
          for key in self._keys():
              try: self.__delitem__(key) #XXX: optionally delete data ?
              except: pass #XXX: don't catch ?
          return
      clear.__doc__ = dict.clear.__doc__
      def copy(self, name=None): #XXX: always None? or allow other settings?
          "D.copy(name) -> a copy of D, with a new archive at the given name"
          if name is None: name = self.name
          else: pass #FIXME: copy database/table instead of do update below
          adict = {'serialized':self.__state__['serialized'], 'database':name}
          adict.update(self.__state__['config'])
          adict = sql_archive(**adict)#FIXME: should reference, not copy
          adict.update(self.__asdict__())
          return adict
      def fromkeys(self, *args): #XXX: build a dict (not an archive)?
          return dict.fromkeys(*args)
      fromkeys.__doc__ = dict.fromkeys.__doc__
      def get(self, key, value=None):
          try: _value = self.__getitem__(key)
          except KeyError: _value = value
          return _value
      get.__doc__ = dict.get.__doc__
      def __contains__(self, key):
          return key in self._keys()
      __contains__.__doc__ = dict.__contains__.__doc__
      if getattr(dict, 'has_key', None):
          has_key = __contains__
          has_key.__doc__ = dict.has_key.__doc__
          def __iter__(self):
              return self._tables().iterkeys()
          def iteritems(self): #XXX: should be dictionary-itemiterator
              keys = self._tables()
              return ((key,self.__getitem__(key)) for key in keys)
          iteritems.__doc__ = dict.iteritems.__doc__
          iterkeys = __iter__
          iterkeys.__doc__ = dict.iterkeys.__doc__
          def itervalues(self): #XXX: should be dictionary-valueiterator
              keys = self._tables()
              return (self.__getitem__(key) for key in keys)
          itervalues.__doc__ = dict.itervalues.__doc__
      else:
          def __iter__(self):
              return iter(self._keys())
      __iter__.__doc__ = dict.__iter__.__doc__
      def keys(self):
          if sys.version_info[0] < 3:
              return self._keys()
          else: return KeysView(self) #XXX: show keys not dict
      keys.__doc__ = dict.keys.__doc__
      def items(self):
          if sys.version_info[0] < 3:
              keys = self._tables()
              return [(key,self.__getitem__(key)) for key in keys]
          else: return ItemsView(self) #XXX: show items not dict
      items.__doc__ = dict.items.__doc__
      def values(self):
          if sys.version_info[0] < 3:
              keys = self._tables()
              return [self.__getitem__(key) for key in keys]
          else: return ValuesView(self) #XXX: show values not dict
      values.__doc__ = dict.values.__doc__
      if _view:
          def viewkeys(self):
              return KeysView(self) #XXX: show keys not dict
          viewkeys.__doc__ = dict.viewkeys.__doc__
          def viewvalues(self):
              return ValuesView(self) #XXX: show values not dict
          viewvalues.__doc__ = dict.viewvalues.__doc__
          def viewitems(self):
              return ItemsView(self) #XXX: show items not dict
          viewitems.__doc__ = dict.viewitems.__doc__
      def pop(self, key, *value):
          try:
              memo = {key: self.__getitem__(key)}
              self.__delitem__(key)
          except:
              memo = {}
          res = memo.pop(key, *value)
          return res
      pop.__doc__ = dict.pop.__doc__
      def popitem(self):
          key = self.__iter__()
          try: key = key.next()
          except StopIteration: raise KeyError("popitem(): dictionary is empty")
          return (key, self.pop(key))
      popitem.__doc__ = dict.popitem.__doc__
      def setdefault(self, key, *value):
          res = self.get(key, *value)
          self.__setitem__(key, res)
          return res
      setdefault.__doc__ = dict.setdefault.__doc__
      def update(self, adict, **kwds):
          if hasattr(adict,'__asdict__'): adict = adict.__asdict__()
          memo = {}
          memo.update(adict, **kwds) #XXX: could be better ?
          for (key,val) in memo.items():
              self.__setitem__(key,val)
          return
      update.__doc__ = dict.update.__doc__
      def __len__(self):
          return len(self._keys())
      def _mktable(self, key):
          "create table corresponding to given key"
          try: return self._gettable(key, meta=True) # table exists
          except KeyError: table = key # table doesn't exist in metadata
          # prepare table types #XXX: do in __init__ ?
          keytype = String(255)
          if self.__state__['serialized']: valtype = PickleType(pickler=dill)
          else: valtype = Text()
          # create table, if doesn't exist
          table = Table(table, self._metadata,
              Column(self._key, keytype, primary_key=True),
              Column(self._val, valtype)
          )
          # initialize
          self._metadata.create_all(self._engine)
          return table
      def _gettable(self, key, meta=False):
          "get table corresponding to given key"
          table = str(key)
          if meta: return self._metadata.tables[table]
          # otherwise, look at all the tables in the database
          if table in self._keys(): return self._mktable(table)
          # if you are here... raise a KeyError
          tables = {}
          return tables[table]
      def _keys(self, meta=False):
          "get a list of tables in the database" #FIXME: with matching self._key
          if meta: return self._metadata.tables.keys()
          # look at all the tables in the database
          names = self._engine.table_names()
          names = [str(name) for name in names]
          # clean up metadata by removing stale tables
          tables = set(self._metadata.tables.keys()) - set(names) #XXX: slow?
          tables = [self._gettable(key, meta=True) for key in tables]
          [self._metadata.remove(key) for key in tables]
          return names
      def _tables(self, meta=False):
          "get a dict of tables in the database"
          if meta: return self._metadata.tables
          # otherwise, look at all the tables in the database
          keys = self._keys()
          return dict((key,self._mktable(key)) for key in keys) #XXX: immutable
      def _primary(self, key): #XXX: faster if value is table['key'].name ?
          "get table primary key corresponding to given key"
          table = self._gettable(key)
          return table.c[self._key]
      # interface
      def load(self, *args):
          """does nothing. required to use an archive as a cache"""
          return
      dump = load
      def archived(self, *on):
          """check if the cache is a persistent archive"""
          L = len(on)
          if not L: return True
          if L > 1: raise TypeError("archived expected at most 1 argument, got %s" % str(L+1))
          raise ValueError("cannot toggle archive")
      def sync(self, clear=False):
          "does nothing. required to use an archive as a cache"
          pass
      def drop(self): #XXX: or actually drop the backend?
          "set the current archive to NULL"
          return self.__archive(None)
      def open(self, archive):
          "replace the current archive with the archive provided"
          return self.__archive(archive)
      def __get_archive(self):
          return self
      def __get_name(self):
          return self.__state__['database']
      def __archive(self, archive):
          raise ValueError("cannot set new archive")
      archive = property(__get_archive, __archive)
      name = property(__get_name, __archive)
      pass

  class sqltable_archive(dict):
      """dictionary-style interface to a sql database table"""
      def __init__(self, database=None, table=None, **kwds):
          """initialize a sql database with a synchronized dictionary interface

      Connect to an existing database, or initialize a new database, at the
      selected database url. For example, to use a sqlite database 'foo.db'
      in the current directory, database='sqlite:///foo.db'.  To use a mysql
      database 'foo' on localhost, database='mysql://user:pass@localhost/foo'.
      For postgresql, use database='postgresql://user:pass@localhost/foo'. 
      When connecting to sqlite, the default database is ':memory:'; otherwise,
      the default database is 'defaultdb'.  Allows keyword options for database
      configuration, such as connection pooling.

      Inputs:
          database: url of the database backend [default: sqlite:///:memory:]
          table: name of the associated database table [default: 'memo']
          serialized: if True, pickle table contents; otherwise cast as strings
          """
          if table is None: table = 'memo' #XXX: better random unique id ?
          # create database, if doesn't exist
          if database is None: database = 'sqlite:///:memory:'
          elif database == 'sqlite:///': database = 'sqlite:///:memory:'
          _database = database
          try:
              url, dbname = _database.rsplit('/', 1)
          except ValueError: # only dbname given
              url, dbname = 'sqlite://', _database
              _database = "%s/%s" % (url,dbname)
          if url.endswith(":/") or dbname == '': # then no dbname was given
              url = _database
              dbname = 'defaultdb'
              _database = "%s/%s" % (url,dbname)
          # set state
          self.__state__ = {
              'serialized': bool(kwds.pop('serialized', True)),
              'database': _database,
              'table': table,
              # preserve other settings (for copy)
              'config': kwds.copy()
          } #XXX: _engine and _metadata (and _key and _val) also __state__ ?
          # get engine
          if dbname == ':memory:':
              self._engine = create_engine(url, **kwds)
          elif _database.startswith('sqlite'):
              self._engine = create_engine(_database, **kwds)
          else:
              self._engine = create_engine(url) #XXX: **kwds ?
              try:
                  conn = self._engine.connect()
                  if _database.startswith('postgres'):
                      conn.connection.connection.set_isolation_level(0)
                  conn.execute("CREATE DATABASE %s;" % dbname)
              except Exception: pass
              finally:
                  if _database.startswith('postgres'):
                      conn.connection.connection.set_isolation_level(1)
              try:
                  self._engine.execute("USE %s;" % dbname)
              except Exception:
                  pass
              self._engine = create_engine(_database, **kwds)
          # prepare to create table
          self._metadata = MetaData()
          self._key = 'Kkey' # primary key name
          self._val = 'Kval' # object storage name
          keytype = String(255) #XXX: other better fixed size?
          if self.__state__['serialized']:
              valtype = PickleType(pickler=dill)
          else:
              valtype = Text() #XXX: String(255) or BLOB() ???
          # create table, if doesn't exist
          if isinstance(table, str): #XXX: better str-variants ? or no if ?
              table = Table(table, self._metadata,
                  Column(self._key, keytype, primary_key=True),
                  Column(self._val, valtype)
              )
          self._key = table.c[self._key]
          self.__state__['table'] = table
          # initialize
          self._metadata.create_all(self._engine)
          return
      def __drop__(self, **kwds):
          """drop the database table

      EXPERIMENTAL: also drop the associated database. For certain
      database engines, this may not work due to permission issues.
      Caller may need to be connected as a superuser and database owner.
      To drop associated database, use __drop__(database=True)
          """
          if not bool(kwds.get('database', False)):
              self.__state__['table'].drop(self._engine) #XXX: or delete data ?
              self._metadata.remove(self.__state__['table'])
              self._metadata = self._engine = self.__state__['table'] = None
              return
          _database = self.__state__['database']
          url, dbname = _database.rsplit('/', 1)
          self._engine = create_engine(url)
          try:
              conn = self._engine.connect()
              if _database.startswith('postgres'):
                  # these two commands require superuser privs
                  conn.execute("update pg_database set datallowconn = 'false' WHERE datname = '%s';" % dbname)
                  conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '%s';" % dbname) # 'pid' used in postgresql >= 9.2
                  conn.connection.connection.set_isolation_level(0)
              conn.execute("DROP DATABASE %s;" % dbname) # must be db owner
              if _database.startswith('postgres'):
                  conn.connection.connection.set_isolation_level(1)
          except Exception:
              dbpath = _database.split('///')[-1]
              if os.path.exists(dbpath): # else fail silently
                  os.remove(dbpath)
          self._metadata = self._engine = self.__state__['table'] = None
          return
      def __len__(self):
          query = self.__state__['table'].count()
          return int(self._engine.execute(query).scalar())
      def __contains__(self, key):
          query = select([self._key], self._key == key)
          row = self._engine.execute(query).fetchone()
          return row is not None
      __contains__.__doc__ = dict.__contains__.__doc__
      def __setitem__(self, key, value):
          value = {self._val: value} #XXX: force into single item dict...?
          table = self.__state__['table']
          if key in self:
              values = value
              query = table.update().where(self._key == key)
          else:
              values = {self._key.name: key}
              values.update(value)
              query = table.insert()
          self._engine.execute(query.values(**values))
          return
      __setitem__.__doc__ = dict.__setitem__.__doc__
      #FIXME: missing __cmp__, __...__
      def __eq__(self, y):
          try:
              if y.__module__ != self.__module__: return NotImplemented
              return self.__asdict__() == y.__asdict__() #XXX: faster than get?
             #if len(self) != len(y): return False
             #try: s = min(k for k in self if self.get(k) != y.get(k))
             #except ValueError: s = []
             #try: v = min(k for k in y if y.get(k) != self.get(k))
             #except ValueError: v = []
             #if s != v: return False
             #elif s == []: return True
             #return self[s] == y[v]
          except: return NotImplemented
      __eq__.__doc__ = dict.__eq__.__doc__
      def __ne__(self, y):
          y = self.__eq__(y)
          return NotImplemented if y is NotImplemented else not y
      __ne__.__doc__ = dict.__ne__.__doc__
      def __delitem__(self, key):
          try: self.pop(key) #FIXME: faster without value lookup
          except KeyError:
              memo = {}
              memo.__delitem__(key)
          return
      __delitem__.__doc__ = dict.__delitem__.__doc__
      def __getitem__(self, key):
          query = select([self.__state__['table']], self._key == key)
          row = self._engine.execute(query).fetchone()
          if row is None: raise KeyError(key)
          return row[self._val]
      __getitem__.__doc__ = dict.__getitem__.__doc__
      def __iter__(self): #XXX: should be dictionary-keyiterator
          query = select([self._key])
          result = self._engine.execute(query)
          for row in result:
              yield row[0]
      __iter__.__doc__ = dict.__iter__.__doc__
      def get(self, key, value=None):
          query = select([self.__state__['table']], self._key == key)
          row = self._engine.execute(query).fetchone()
          if row != None:
              _value = row[self._val]
          else: _value = value
          return _value
      get.__doc__ = dict.get.__doc__
      def clear(self):
          query = self.__state__['table'].delete()
          self._engine.execute(query)
          return
      clear.__doc__ = dict.clear.__doc__
     #def insert(self, d): #XXX: don't allow this method, or hide ?
     #    query = self.__state__['table'].insert(d)
     #    self._engine.execute(query)
     #    return
      def copy(self, name=None): #XXX: always None? or allow other settings?
          "D.copy(name) -> a copy of D, with a new archive at the given name"
          if name is None: name = self.name
          else: pass #FIXME: copy database/table instead of do update below
          db,table = _sqlname(name)
          adict = {'serialized': self.__state__['serialized'],\
                   'database': db, 'table': table}
          adict.update(self.__state__['config'])
          adict = sqltable_archive(**adict) #FIXME: should reference, not copy
          adict.update(self.__asdict__())
          return adict
      def fromkeys(self, *args): #XXX: build a dict (not an archive)?
          return dict.fromkeys(*args)
      fromkeys.__doc__ = dict.fromkeys.__doc__
      def __asdict__(self):
          """build a dictionary containing the archive contents"""
          if getattr(dict, 'iteritems', None):
              return dict(self.iteritems())
          else: return dict(self.items())
      def __repr__(self):
          return "sqltable_archive('%s' %s, cached=False)" % (self.name, self.__asdict__())
      __repr__.__doc__ = dict.__repr__.__doc__
      if getattr(dict, 'has_key', None):
          def has_key(self, key): #XXX: different than contains... why?
              query = select([self.__state__['table']], self._key == key)
              row = self._engine.execute(query).fetchone()
              return row != None
          has_key.__doc__ = dict.has_key.__doc__
          def iteritems(self): #XXX: should be dictionary-itemiterator
              query = select([self.__state__['table']])
              result = self._engine.execute(query)
              for row in result:
                  yield (row[0], row[self._val])
          iteritems.__doc__ = dict.iteritems.__doc__
          iterkeys = __iter__
          iterkeys.__doc__ = dict.iterkeys.__doc__
          def itervalues(self): #XXX: should be dictionary-valueiterator
              query = select([self.__state__['table']])
              result = self._engine.execute(query)
              for row in result:
                  yield row[self._val]
          itervalues.__doc__ = dict.itervalues.__doc__
          def keys(self):
              return list(self.__iter__())
          def items(self):
              return list(self.iteritems())
          def values(self):
              return list(self.itervalues())
      else:
          def keys(self):
              return KeysView(self) #XXX: show keys not dict
          def items(self):
              return ItemsView(self) #XXX: show keys not dict
          def values(self):
              return ValuesView(self) #XXX: show keys not dict
      keys.__doc__ = dict.keys.__doc__
      items.__doc__ = dict.items.__doc__
      values.__doc__ = dict.values.__doc__
      if _view:
          def viewkeys(self):
              return KeysView(self) #XXX: show keys not dict
          viewkeys.__doc__ = dict.viewkeys.__doc__
          def viewvalues(self):
              return ValuesView(self) #XXX: show values not dict
          viewvalues.__doc__ = dict.viewvalues.__doc__
          def viewitems(self):
              return ItemsView(self) #XXX: show items not dict
          viewitems.__doc__ = dict.viewitems.__doc__
      def pop(self, key, *value):
          L = len(value)
          if L > 1:
              raise TypeError("pop expected at most 2 arguments, got %s" % str(L+1))
          query = select([self.__state__['table']], self._key == key)
          row = self._engine.execute(query).fetchone()
          if row != None:
              _value = row[self._val]
          else:
              if not L: raise KeyError(key)
              _value = value[0]
          query = delete(self.__state__['table'], self._key == key)
          self._engine.execute(query)
          return _value
      pop.__doc__ = dict.pop.__doc__
      def popitem(self):
          key = self.__iter__()
          try: key = key.next()
          except StopIteration: raise KeyError("popitem(): dictionary is empty")
          return (key, self.pop(key))
      popitem.__doc__ = dict.popitem.__doc__
      def setdefault(self, key, *value):
          L = len(value)
          if L > 1:
              raise TypeError("setvalue expected at most 2 arguments, got %s" % str(L+1))
          query = select([self.__state__['table']], self._key == key)
          row = self._engine.execute(query).fetchone()
          if row != None:
              _value = row[self._val]
          else:
              if not L: _value = None
              else: _value = value[0]
              self.__setitem__(key, _value)
          return _value
      setdefault.__doc__ = dict.setdefault.__doc__
      def update(self, adict, **kwds):
          if hasattr(adict,'__asdict__'): adict = adict.__asdict__()
          else: adict = adict.copy()
          adict.update(**kwds)
          [self.__setitem__(k,v) for (k,v) in adict.items()]
          return #XXX: should do the above all at once, and more efficiently
      update.__doc__ = dict.update.__doc__
      # interface
      def load(self, *args):
          """does nothing. required to use an archive as a cache"""
          return
      dump = load
      def archived(self, *on):
          """check if the cache is a persistent archive"""
          L = len(on)
          if not L: return True
          if L > 1: raise TypeError("archived expected at most 1 argument, got %s" % str(L+1))
          raise ValueError("cannot toggle archive")
      def sync(self, clear=False):
          "does nothing. required to use an archive as a cache"
          pass
      def drop(self): #XXX: or actually drop the backend?
          "set the current archive to NULL"
          return self.__archive(None)
      def open(self, archive):
          "replace the current archive with the archive provided"
          return self.__archive(archive)
      def __get_archive(self):
          return self
      def __get_name(self):
          return "%s?table=%s" % (self.__state__['database'], self.__state__['table'])
      def __archive(self, archive):
          raise ValueError("cannot set new archive")
      archive = property(__get_archive, __archive)
      name = property(__get_name, __archive)
      pass
else:
  class sqltable_archive(dict): #XXX: requires UTF-8 key; #FIXME: use sqlite3.dbapi2
      """dictionary-style interface to a sql database table"""
      def __init__(self, database=None, table=None, **kwds): #serialized
          """initialize a sql database with a synchronized dictionary interface

      Connect to an existing database, or initialize a new database, at the
      selected database url. For example, to use a sqlite database 'foo.db'
      in the current directory, database='sqlite:///foo.db'.  To use a mysql
      or postgresql database, sqlalchemy must be installed.  When connecting
      to sqlite, the default database is ':memory:'.  Storable values are
      limited to strings, integers, floats, and other basic objects.  To store
      functions, classes, and similar constructs, sqlalchemy must be installed.

      Inputs:
          database: url of the database backend [default: sqlite:///:memory:]
          table: name of the associated database table [default: 'memo']
          """
          import sqlite3 as db
          if table is None: table = 'memo'
          # create database, if doesn't exist
          if database is None: database = 'sqlite:///:memory:'
          elif database == 'sqlite:///': database = 'sqlite:///:memory:'
          _database = database
          if not _database.startswith('sqlite:///'):
              if _database.count(':')+_database.count('/'):
                  raise ValueError("install sqlalchemy for non-sqlite database support")
              _database = 'sqlite:///'+_database
          dbname = _database.split('sqlite:///')[-1]
          # set state
          kwds.pop('serialized', True) # 'serialized' is not available
          self.__state__ = {
              'serialized': False,
              'database': _database,
              'table': table,
              # preserve other settings (for copy)
              'config': kwds.copy()
          } #XXX: _engine and _metadata (and _key and _val) also __state__ ?
          # create table, if doesn't exist
          self._conn = db.connect(dbname)
          self._engine = self._conn.cursor()
          sql = "create table if not exists %s(argstr, fval)" % table
          self._engine.execute(sql)
          # compatibility
          self._metadata = None
          self._key = 'Kkey'
          self._val = 'Kval'
          return
      def __drop__(self, **kwds):
          """drop the database table

      EXPERIMENTAL: also drop the associated database. For certain
      database engines, this may not work due to permission issues.
      Caller may need to be connected as a superuser and database owner.
      To drop associated database, use __drop__(database=True)
          """
          if not bool(kwds.get('database', False)):
              self._engine.executescript('drop table if exists %s;' % self.__state__['table'])
              self._engine = self._conn = self.__state__['table'] = None
              return
          _database = self.__state__['database']
          try:
              dbname = _database.lstrip('sqlite:///')
              conn = db.connect(':memory:')
              conn.execute("DROP DATABASE %s;" % dbname) #FIXME: always fails
          except Exception:
              dbpath = _database.split('///')[-1]
              if os.path.exists(dbpath): # else fail silently
                  os.remove(dbpath)
          self._engine = self._conn = self.__state__['table'] = None
          return
      def __len__(self):
          return len(self.__asdict__())
      def __contains__(self, key):
          return bool(self._select_key_items(key))
      __contains__.__doc__ = dict.__contains__.__doc__
      def __setitem__(self, key, value): #XXX: maintains 'history' of values
          sql = "insert into %s values(?,?)" % self.__state__['table']
          self._engine.execute(sql, (key,value))
          self._conn.commit()
          return
      __setitem__.__doc__ = dict.__setitem__.__doc__
      #FIXME: missing __cmp__, __...__
      def __eq__(self, y):
          try:
              if y.__module__ != self.__module__: return NotImplemented
              return self.__asdict__() == y.__asdict__() #XXX: faster than get?
             #if len(self) != len(y): return False
             #try: s = min(k for k in self if self.get(k) != y.get(k))
             #except ValueError: s = []
             #try: v = min(k for k in y if y.get(k) != self.get(k))
             #except ValueError: v = []
             #if s != v: return False
             #elif s == []: return True
             #return self[s] == y[v]
          except: return NotImplemented
      __eq__.__doc__ = dict.__eq__.__doc__
      def __ne__(self, y):
          y = self.__eq__(y)
          return NotImplemented if y is NotImplemented else not y
      __ne__.__doc__ = dict.__ne__.__doc__
      def __delitem__(self, key):
          try: self.pop(key) #FIXME: faster without value lookup
          except KeyError:
              memo = {}
              memo.__delitem__(key)
          return
      __delitem__.__doc__ = dict.__delitem__.__doc__
      def __getitem__(self, key):
          res = self._select_key_items(key)
          if res: return res[-1][-1] # always get the last one
          raise KeyError(key)
      __getitem__.__doc__ = dict.__getitem__.__doc__
      def __iter__(self): #XXX: should be dictionary-keyiterator
          sql = "select argstr from %s" % self.__state__['table']
          return (k[-1] for k in set(self._engine.execute(sql)))
      __iter__.__doc__ = dict.__iter__.__doc__
      def get(self, key, value=None):
          res = self._select_key_items(key)
          if res: value = res[-1][-1]
          return value
      get.__doc__ = dict.get.__doc__
      def clear(self):
          [self.pop(k) for k in self.keys()] # better delete table, add empty ?
          return
      clear.__doc__ = dict.clear.__doc__
      def copy(self, name=None): #XXX: always None? or allow other settings?
          "D.copy(name) -> a copy of D, with a new archive at the given name"
          if name is None: name = self.name
          else: pass #FIXME: copy database/table instead of do update below
          db,table = _sqlname(name)
          adict = {'serialized': self.__state__['serialized'],\
                   'database': db, 'table': table}
          adict.update(self.__state__['config'])
          adict = sqltable_archive(**adict) #FIXME: should reference, not copy
          adict.update(self.__asdict__())
          return adict
      def fromkeys(self, *args): #XXX: build a dict (not an archive)?
          return dict.fromkeys(*args)
      fromkeys.__doc__ = dict.fromkeys.__doc__
      def __asdict__(self):
          """build a dictionary containing the archive contents"""
          sql = "select * from %s" % self.__state__['table']
          res = self._engine.execute(sql)
          d = {}
          [d.update({k:v}) for (k,v) in res] # always get the last one
          return d
      def __repr__(self):
          return "sqltable_archive('%s' %s, cached=False)" % (self.name, self.__asdict__())
      __repr__.__doc__ = dict.__repr__.__doc__
      if getattr(dict, 'has_key', None):
          has_key = __contains__
          has_key.__doc__ = dict.has_key.__doc__
          def iteritems(self): #XXX: should be dictionary-itemiterator
              return ((k,self.__getitem__(k)) for k in self.__iter__())
          iteritems.__doc__ = dict.iteritems.__doc__
          iterkeys = __iter__
          iterkeys.__doc__ = dict.iterkeys.__doc__
          def itervalues(self): #XXX: should be dictionary-valueiterator
              return (self.__getitem__(k) for k in self.__iter__())
          itervalues.__doc__ = dict.itervalues.__doc__
          def keys(self):
              return list(self.__iter__())
          def items(self):
              return list(self.iteritems())
          def values(self):
              return list(self.itervalues())
      else:
          def keys(self):
              return KeysView(self) #XXX: show keys not dict
          def items(self):
              return ItemsView(self) #XXX: show keys not dict
          def values(self):
              return ValuesView(self) #XXX: show keys not dict
      keys.__doc__ = dict.keys.__doc__
      items.__doc__ = dict.items.__doc__
      values.__doc__ = dict.values.__doc__
      if _view:
          def viewkeys(self):
              return KeysView(self) #XXX: show keys not dict
          viewkeys.__doc__ = dict.viewkeys.__doc__
          def viewvalues(self):
              return ValuesView(self) #XXX: show values not dict
          viewvalues.__doc__ = dict.viewvalues.__doc__
          def viewitems(self):
              return ItemsView(self) #XXX: show items not dict
          viewitems.__doc__ = dict.viewitems.__doc__
      def pop(self, key, *value):
          L = len(value)
          if L > 1:
              raise TypeError("pop expected at most 2 arguments, got %s" % str(L+1))
          res = self._select_key_items(key)
          if res:
              _value = res[-1][-1]
          else:
              if not L: raise KeyError(key)
              _value = value[0]
          sql = "delete from %s where argstr = ?" % self.__state__['table']
          self._engine.execute(sql, (key,))
          self._conn.commit()
          return _value 
      pop.__doc__ = dict.pop.__doc__
      def popitem(self):
          key = self.__iter__()
          try: key = key.next()
          except StopIteration: raise KeyError("popitem(): dictionary is empty")
          return (key, self.pop(key))
      popitem.__doc__ = dict.popitem.__doc__
      def setdefault(self, key, *value):
          L = len(value)
          if L > 1:
              raise TypeError("setvalue expected at most 2 arguments, got %s" % str(L+1))
          res = self._select_key_items(key)
          if res:
              _value = res[-1][-1]
          else:
              if not L: _value = None
              else: _value = value[0]
              self.__setitem__(key, _value)
          return _value
      setdefault.__doc__ = dict.setdefault.__doc__
      def update(self, adict, **kwds):
          if hasattr(adict,'__asdict__'): adict = adict.__asdict__()
          else: adict = adict.copy()
          adict.update(**kwds)
          [self.__setitem__(k,v) for (k,v) in adict.items()]
          return
      update.__doc__ = dict.update.__doc__
      def _select_key_items(self, key):
          '''Return a tuple of (key, value) pairs that match the specified key'''
          sql = "select * from %s where argstr = ?" % self.__state__['table']
          return tuple(self._engine.execute(sql, (key,)))
      # interface
      def load(self, *args):
          """does nothing. required to use an archive as a cache"""
          return
      dump = load
      def archived(self, *on):
          """check if the cache is a persistent archive"""
          L = len(on)
          if not L: return True
          if L > 1: raise TypeError("archived expected at most 1 argument, got %s" % str(L+1))
          raise ValueError("cannot toggle archive")
      def sync(self, clear=False):
          "does nothing. required to use an archive as a cache"
          pass
      def drop(self): #XXX: or actually drop the backend?
          "set the current archive to NULL"
          return self.__archive(None)
      def open(self, archive):
          "replace the current archive with the archive provided"
          return self.__archive(archive)
      def __get_archive(self):
          return self
      def __get_name(self):
          return "%s?table=%s" % (self.__state__['database'], self.__state__['table'])
      def __archive(self, archive):
          raise ValueError("cannot set new archive")
      archive = property(__get_archive, __archive)
      name = property(__get_name, __archive)
      pass
  sql_archive = sqltable_archive #XXX: or NotImplemented ?


# backward compatibility
archive_dict = cache
db_archive = sqltable_archive

# EOF
