#!/usr/bin/env python
# code inspired by Raymond Hettinger's LFU and LRU cache decorators
# on http://code.activestate.com/recipes/498245-lru-and-lfu-cache-decorators
# and subsequent forks as well as the version available in python3.3
"""
a selection of caching decorators
"""
from __future__ import absolute_import
from collections import deque
from random import choice #XXX: biased?
from heapq import nsmallest
from operator import itemgetter
try:
    from itertools import filterfalse
except ImportError:
    from itertools import ifilterfalse as filterfalse
from functools import update_wrapper
from threading import RLock
from klepto.rounding import deep_round, simple_round
from klepto.archives import cache as archive_dict
from klepto.keymaps import hashmap
from klepto.tools import CacheInfo
from ._inspect import _keygen

__all__ = ['no_cache','inf_cache','lfu_cache',\
           'lru_cache','mru_cache','rr_cache']

class Counter(dict):
    'Mapping where default values are zero'
    def __missing__(self, key):
        return 0

#XXX: what about caches that expire due to time, calls, etc...
#XXX: check the impact of not serializing by default, and hashmap by default

def no_cache(*arg, **kwd):
    '''empty (NO) cache decorator.

    Unlike other cache decorators, this decorator does not cache.  It is a
    dummy that collects statistics and conforms to the caching interface.  This
    decorator takes an integer tolerance 'tol', equal to the number of decimal
    places to which it will round off floats, and a bool 'deep' for whether the
    rounding on inputs will be 'shallow' or 'deep'.

    keymap = cache key encoder (default is keymaps.hashmap(flat=True))
    tol = integer tolerance for rounding (default is None)
    deep = boolean for rounding depth (default is False, i.e. 'shallow')
    ignore = function argument names and indicies to 'ignore' (default is None)

    If *keymap* is given, it will replace the hashing algorithm for generating
    cache keys.  Several hashing algorithms are available in 'keymaps'. The
    default keymap requires arguments to the cached function to be hashable.

    If the keymap retains type information, then arguments of different types
    will be cached separately.  For example, f(3.0) and f(3) will be treated
    as distinct calls with distinct results.  Cache typing has a memory penalty,
    and may also be ignored by some 'keymaps'.  Here, the keymap is only used
    to look up keys in an associated archive.

    If *ignore* is given, the keymap will ignore the arguments with the names
    and/or positional indicies provided. For example, if ignore=(0,), then
    the key generated for f(1,2) will be identical to that of f(3,2) or f(4,2).
    If ignore=('y',), then the key generated for f(x=3,y=4) will be identical
    to that of f(x=3,y=0) or f(x=3,y=10). If ignore=('*','**'), all varargs
    and varkwds will be 'ignored'.  Ignored arguments never trigger a
    recalculation (they only trigger cache lookups), and thus are 'ignored'.
    When caching class methods, it may be useful to ignore=('self',).

    View cache statistics (hit, miss, load, maxsize, size) with f.info().
    Clear the cache and statistics with f.clear().  Replace the cache archive
    with f.archive(obj).  Load from the archive with f.load(), and dump from
    the cache to the archive with f.dump().
    '''
    maxsize = 0

    keymap = kwd.get('keymap', None)
    if keymap is None: keymap = hashmap(flat=True)
    ignore = kwd.get('ignore', None)
    if ignore is None: ignore = tuple()
    cache = archive_dict()

    tol = kwd.get('tol', None)
    deep = kwd.get('deep', False)
    if deep: rounded = deep_round
    else: rounded = simple_round
   #else: rounded = shallow_round #FIXME: slow

    @rounded(tol)
    def rounded_args(*args, **kwds):
        return (args, kwds)

    def decorating_function(user_function):
       #cache = dict()                  # mapping of args to results
        stats = [0, 0, 0]               # make statistics updateable non-locally
        HIT, MISS, LOAD = 0, 1, 2       # names for the stats fields
        _len = len                      # localize the global len() function
       #lock = RLock()                  # linkedlist updates aren't threadsafe

        def wrapper(*args, **kwds):
            _args, _kwds = rounded_args(*args, **kwds)
            _args, _kwds = _keygen(user_function, ignore, *_args, **_kwds)
            key = keymap(*_args, **_kwds)

            # look in archive
            if cache.archived():
                cache.load(key)
            try:
                result = cache[key]
                cache.clear()
                stats[LOAD] += 1
            except KeyError:
                # if not found, then compute
                result = user_function(*args, **kwds)
                cache[key] = result
                stats[MISS] += 1

            # purge cache
            if _len(cache) > maxsize:
                if cache.archived():
                    cache.dump()
                cache.clear() 
            return result

        def archive(obj):
            """Replace the cache archive"""
            cache.archive = obj

        def __get_cache():
            """Get the cache"""
            return cache

        def clear(keepstats=False):
            """Clear the cache and statistics"""
            if not keepstats: stats[:] = [0, 0, 0]

        def info():
            """Report cache statistics"""
            return CacheInfo(stats[HIT], stats[MISS], stats[LOAD], maxsize, len(cache))

        # interface
        wrapper.__wrapped__ = user_function
        #XXX: better is handle to key_function=keygen(ignore)(user_function) ?
        wrapper.info = info
        wrapper.clear = clear
        wrapper.load = cache.load
        wrapper.dump = cache.dump
        wrapper.archive = archive
        wrapper.archived = cache.archived
        wrapper.__cache__ = __get_cache
       #wrapper._queue = None  #XXX
        return update_wrapper(wrapper, user_function)

    return decorating_function


def inf_cache(*arg, **kwd):
    '''infinitely-growing (INF) cache decorator.

    This decorator memoizes a function's return value each time it is called.
    If called later with the same arguments, the cached value is returned, and
    not re-evaluated.  This cache will grow without bound.  To avoid memory
    issues, it is suggested to frequently dump and clear the cache.  This
    decorator takes an integer tolerance 'tol', equal to the number of decimal
    places to which it will round off floats, and a bool 'deep' for whether the
    rounding on inputs will be 'shallow' or 'deep'.

    cache = storage hashmap (default is {})
    keymap = cache key encoder (default is keymaps.hashmap(flat=True))
    tol = integer tolerance for rounding (default is None)
    deep = boolean for rounding depth (default is False, i.e. 'shallow')
    ignore = function argument names and indicies to 'ignore' (default is None)

    If *keymap* is given, it will replace the hashing algorithm for generating
    cache keys.  Several hashing algorithms are available in 'keymaps'. The
    default keymap requires arguments to the cached function to be hashable.

    If the keymap retains type information, then arguments of different types
    will be cached separately.  For example, f(3.0) and f(3) will be treated
    as distinct calls with distinct results.  Cache typing has a memory penalty,
    and may also be ignored by some 'keymaps'.

    If *ignore* is given, the keymap will ignore the arguments with the names
    and/or positional indicies provided. For example, if ignore=(0,), then
    the key generated for f(1,2) will be identical to that of f(3,2) or f(4,2).
    If ignore=('y',), then the key generated for f(x=3,y=4) will be identical
    to that of f(x=3,y=0) or f(x=3,y=10). If ignore=('*','**'), all varargs
    and varkwds will be 'ignored'.  Ignored arguments never trigger a
    recalculation (they only trigger cache lookups), and thus are 'ignored'.
    When caching class methods, it may be useful to ignore=('self',).

    View cache statistics (hit, miss, load, maxsize, size) with f.info().
    Clear the cache and statistics with f.clear().  Replace the cache archive
    with f.archive(obj).  Load from the archive with f.load(), and dump from
    the cache to the archive with f.dump().
    '''
    maxsize = None

    keymap = kwd.get('keymap', None)
    if keymap is None: keymap = hashmap(flat=True)
    ignore = kwd.get('ignore', None)
    if ignore is None: ignore = tuple()
    cache = kwd.get('cache', None)
    if cache is None: cache = archive_dict()
    elif type(cache) is dict: cache = archive_dict(cache)
    # does archive make sense with database, file, ?... (requires more thought)

    tol = kwd.get('tol', None)
    deep = kwd.get('deep', False)
    if deep: rounded = deep_round
    else: rounded = simple_round
   #else: rounded = shallow_round #FIXME: slow

    @rounded(tol)
    def rounded_args(*args, **kwds):
        return (args, kwds)

    def decorating_function(user_function):
       #cache = dict()                  # mapping of args to results
        stats = [0, 0, 0]               # make statistics updateable non-locally
        HIT, MISS, LOAD = 0, 1, 2       # names for the stats fields
       #_len = len                      # localize the global len() function
       #lock = RLock()                  # linkedlist updates aren't threadsafe

        def wrapper(*args, **kwds):
            _args, _kwds = rounded_args(*args, **kwds)
            _args, _kwds = _keygen(user_function, ignore, *_args, **_kwds)
            key = keymap(*_args, **_kwds)

            try:
                # get cache entry
                result = cache[key]
                stats[HIT] += 1
            except KeyError:
                # if not in cache, look in archive
                if cache.archived():
                    cache.load(key)
                try:
                    result = cache[key]
                    stats[LOAD] += 1
                except KeyError:
                    # if not found, then compute
                    result = user_function(*args, **kwds)
                    cache[key] = result
                    stats[MISS] += 1
            return result

        def archive(obj):
            """Replace the cache archive"""
            cache.archive = obj

        def __get_cache():
            """Get the cache"""
            return cache

        def clear(keepstats=False):
            """Clear the cache and statistics"""
            cache.clear()
            if not keepstats: stats[:] = [0, 0, 0]

        def info():
            """Report cache statistics"""
            return CacheInfo(stats[HIT], stats[MISS], stats[LOAD], maxsize, len(cache))

        # interface
        wrapper.__wrapped__ = user_function
        #XXX: better is handle to key_function=keygen(ignore)(user_function) ?
        wrapper.info = info
        wrapper.clear = clear
        wrapper.load = cache.load
        wrapper.dump = cache.dump
        wrapper.archive = archive
        wrapper.archived = cache.archived
        wrapper.__cache__ = __get_cache
       #wrapper._queue = None  #XXX
        return update_wrapper(wrapper, user_function)

    return decorating_function


def lfu_cache(maxsize=100, cache=None, keymap=None, ignore=None, tol=None, deep=False):
    '''least-frequenty-used (LFU) cache decorator.

    This decorator memoizes a function's return value each time it is called.
    If called later with the same arguments, the cached value is returned, and
    not re-evaluated.  To avoid memory issues, a maximum cache size is imposed.
    For caches with an archive, the full cache dumps to archive upon reaching
    maxsize. For caches without an archive, the LFU algorithm manages the cache.
    This decorator takes an integer tolerance 'tol', equal to the number of
    decimal places to which it will round off floats, and a bool 'deep' for
    whether the rounding on inputs will be 'shallow' or 'deep'.

    maxsize = maximum cache size
    cache = storage hashmap (default is {})
    keymap = cache key encoder (default is keymaps.hashmap(flat=True))
    tol = integer tolerance for rounding (default is None)
    deep = boolean for rounding depth (default is False, i.e. 'shallow')
    ignore = function argument names and indicies to 'ignore' (default is None)

    If *maxsize* is None, this cache will grow without bound.

    If *keymap* is given, it will replace the hashing algorithm for generating
    cache keys.  Several hashing algorithms are available in 'keymaps'. The
    default keymap requires arguments to the cached function to be hashable.

    If the keymap retains type information, then arguments of different types
    will be cached separately.  For example, f(3.0) and f(3) will be treated
    as distinct calls with distinct results.  Cache typing has a memory penalty,
    and may also be ignored by some 'keymaps'.

    If *ignore* is given, the keymap will ignore the arguments with the names
    and/or positional indicies provided. For example, if ignore=(0,), then
    the key generated for f(1,2) will be identical to that of f(3,2) or f(4,2).
    If ignore=('y',), then the key generated for f(x=3,y=4) will be identical
    to that of f(x=3,y=0) or f(x=3,y=10). If ignore=('*','**'), all varargs
    and varkwds will be 'ignored'.  Ignored arguments never trigger a
    recalculation (they only trigger cache lookups), and thus are 'ignored'.
    When caching class methods, it may be useful to ignore=('self',).

    View cache statistics (hit, miss, load, maxsize, size) with f.info().
    Clear the cache and statistics with f.clear().  Replace the cache archive
    with f.archive(obj).  Load from the archive with f.load(), and dump from
    the cache to the archive with f.dump().

    See: http://en.wikipedia.org/wiki/Cache_algorithms#Least_Frequently_Used
    '''
    if maxsize == 0:
        return no_cache(cache=cache, keymap=keymep, ignore=ignore, tol=tol, deep=deep)
    if maxsize is None:
        return inf_cache(cache=cache, keymap=keymap, ignore=ignore, tol=tol, deep=deep)

    if keymap is None: keymap = hashmap(flat=True)
    if ignore is None: ignore = tuple()
    if cache is None: cache = archive_dict()
    elif type(cache) is dict: cache = archive_dict(cache)
    # does archive make sense with database, file, ?... (requires more thought)

    if deep: rounded = deep_round
    else: rounded = simple_round
   #else: rounded = shallow_round #FIXME: slow

    @rounded(tol)
    def rounded_args(*args, **kwds):
        return (args, kwds)

    def decorating_function(user_function):
       #cache = dict()                  # mapping of args to results
        use_count = Counter()           # times each key has been accessed
        stats = [0, 0, 0]               # make statistics updateable non-locally
        HIT, MISS, LOAD = 0, 1, 2       # names for the stats fields
        _len = len                      # localize the global len() function
       #lock = RLock()                  # linkedlist updates aren't threadsafe

        def wrapper(*args, **kwds):
            _args, _kwds = rounded_args(*args, **kwds)
            _args, _kwds = _keygen(user_function, ignore, *_args, **_kwds)
            key = keymap(*_args, **_kwds)

            try:
                # get cache entry
                result = cache[key]
                use_count[key] += 1
                stats[HIT] += 1
            except KeyError:
                # if not in cache, look in archive
                if cache.archived():
                    cache.load(key)
                try:
                    result = cache[key]
                    use_count[key] += 1
                    stats[LOAD] += 1
                except KeyError:
                    # if not found, then compute
                    result = user_function(*args, **kwds)
                    cache[key] = result
                    use_count[key] += 1
                    stats[MISS] += 1

                # purge cache
                if _len(cache) > maxsize:
                    if cache.archived():
                        cache.dump()
                        cache.clear() 
                        use_count.clear()
                    else: # purge least frequent cache entries
                        for k, _ in nsmallest(max(2, maxsize // 10),
                                              iter(use_count.items()),
                                              key=itemgetter(1)):
                            del cache[k], use_count[k]
            return result

        def archive(obj):
            """Replace the cache archive"""
            cache.archive = obj

        def __get_cache():
            """Get the cache"""
            return cache

        def clear(keepstats=False):
            """Clear the cache and statistics"""
            cache.clear()
            use_count.clear()
            if not keepstats: stats[:] = [0, 0, 0]

        def info():
            """Report cache statistics"""
            return CacheInfo(stats[HIT], stats[MISS], stats[LOAD], maxsize, len(cache))

        # interface
        wrapper.__wrapped__ = user_function
        #XXX: better is handle to key_function=keygen(ignore)(user_function) ?
        wrapper.info = info
        wrapper.clear = clear
        wrapper.load = cache.load
        wrapper.dump = cache.dump
        wrapper.archive = archive
        wrapper.archived = cache.archived
        wrapper.__cache__ = __get_cache
       #wrapper._queue = use_count #XXX
        return update_wrapper(wrapper, user_function)

    return decorating_function


def lru_cache(maxsize=100, cache=None, keymap=None, ignore=None, tol=None, deep=False):
    '''least-recently-used (LRU) cache decorator.

    This decorator memoizes a function's return value each time it is called.
    If called later with the same arguments, the cached value is returned, and
    not re-evaluated.  To avoid memory issues, a maximum cache size is imposed.
    For caches with an archive, the full cache dumps to archive upon reaching
    maxsize. For caches without an archive, the LRU algorithm manages the cache.
    This decorator takes an integer tolerance 'tol', equal to the number of
    decimal places to which it will round off floats, and a bool 'deep' for
    whether the rounding on inputs will be 'shallow' or 'deep'.

    maxsize = maximum cache size
    cache = storage hashmap (default is {})
    keymap = cache key encoder (default is keymaps.hashmap(flat=True))
    tol = integer tolerance for rounding (default is None)
    deep = boolean for rounding depth (default is False, i.e. 'shallow')
    ignore = function argument names and indicies to 'ignore' (default is None)

    If *maxsize* is None, this cache will grow without bound.

    If *keymap* is given, it will replace the hashing algorithm for generating
    cache keys.  Several hashing algorithms are available in 'keymaps'. The
    default keymap requires arguments to the cached function to be hashable.

    If the keymap retains type information, then arguments of different types
    will be cached separately.  For example, f(3.0) and f(3) will be treated
    as distinct calls with distinct results.  Cache typing has a memory penalty,
    and may also be ignored by some 'keymaps'.

    If *ignore* is given, the keymap will ignore the arguments with the names
    and/or positional indicies provided. For example, if ignore=(0,), then
    the key generated for f(1,2) will be identical to that of f(3,2) or f(4,2).
    If ignore=('y',), then the key generated for f(x=3,y=4) will be identical
    to that of f(x=3,y=0) or f(x=3,y=10). If ignore=('*','**'), all varargs
    and varkwds will be 'ignored'.  Ignored arguments never trigger a
    recalculation (they only trigger cache lookups), and thus are 'ignored'.
    When caching class methods, it may be useful to ignore=('self',).

    View cache statistics (hit, miss, load, maxsize, size) with f.info().
    Clear the cache and statistics with f.clear().  Replace the cache archive
    with f.archive(obj).  Load from the archive with f.load(), and dump from
    the cache to the archive with f.dump().

    See: http://en.wikipedia.org/wiki/Cache_algorithms#Least_Recently_Used
    '''
    if maxsize == 0:
        return no_cache(cache=cache, keymap=keymep, ignore=ignore, tol=tol, deep=deep)
    if maxsize is None:
        return inf_cache(cache=cache, keymap=keymap, ignore=ignore, tol=tol, deep=deep)
    maxqueue = maxsize * 10 #XXX: user settable? confirm this works as expected

    if keymap is None: keymap = hashmap(flat=True)
    if ignore is None: ignore = tuple()
    if cache is None: cache = archive_dict()
    elif type(cache) is dict: cache = archive_dict(cache)
    # does archive make sense with database, file, ?... (requires more thought)

    if deep: rounded = deep_round
    else: rounded = simple_round
   #else: rounded = shallow_round #FIXME: slow

    @rounded(tol)
    def rounded_args(*args, **kwds):
        return (args, kwds)

    def decorating_function(user_function):
       #cache = dict()                  # mapping of args to results
        queue = deque()                 # order that keys have been used
        refcount = Counter()            # times each key is in the queue
        sentinel = object()             # marker for looping around the queue
        stats = [0, 0, 0]               # make statistics updateable non-locally
        HIT, MISS, LOAD = 0, 1, 2       # names for the stats fields
        _len = len                      # localize the global len() function
       #lock = RLock()                  # linkedlist updates aren't threadsafe

        # lookup optimizations (ugly but fast)
        queue_append, queue_popleft = queue.append, queue.popleft
        queue_appendleft, queue_pop = queue.appendleft, queue.pop

        def wrapper(*args, **kwds):
            _args, _kwds = rounded_args(*args, **kwds)
            _args, _kwds = _keygen(user_function, ignore, *_args, **_kwds)
            key = keymap(*_args, **_kwds)

            try:
                # get cache entry
                result = cache[key]
                # record recent use of this key
                queue_append(key)
                refcount[key] += 1
                stats[HIT] += 1
            except KeyError:
                # if not in cache, look in archive
                if cache.archived():
                    cache.load(key)
                try:
                    result = cache[key]
                    # record recent use of this key
                    queue_append(key)
                    refcount[key] += 1
                    stats[LOAD] += 1
                except KeyError:
                    # if not found, then compute
                    result = user_function(*args, **kwds)
                    cache[key] = result
                    # record recent use of this key
                    queue_append(key)
                    refcount[key] += 1
                    stats[MISS] += 1

                # purge cache
                if _len(cache) > maxsize:
                    if cache.archived():
                        cache.dump()
                        cache.clear() 
                        queue.clear()
                        refcount.clear()
                    else: # purge least recently used cache entry
                        key = queue_popleft()
                        refcount[key] -= 1
                        while refcount[key]:
                            key = queue_popleft()
                            refcount[key] -= 1
                        del cache[key], refcount[key]

            # periodically compact the queue by eliminating duplicate keys
            # while preserving order of most recent access
            if _len(queue) > maxqueue:
                refcount.clear()
                queue_appendleft(sentinel)
                for key in filterfalse(refcount.__contains__,
                                        iter(queue_pop, sentinel)):
                    queue_appendleft(key)
                    refcount[key] = 1
            return result

        def archive(obj):
            """Replace the cache archive"""
            cache.archive = obj

        def __get_cache():
            """Get the cache"""
            return cache

        def clear(keepstats=False):
            """Clear the cache and statistics"""
            cache.clear()
            queue.clear()
            refcount.clear()
            if not keepstats: stats[:] = [0, 0, 0]

        def info():
            """Report cache statistics"""
            return CacheInfo(stats[HIT], stats[MISS], stats[LOAD], maxsize, len(cache))

        # interface
        wrapper.__wrapped__ = user_function
        #XXX: better is handle to key_function=keygen(ignore)(user_function) ?
        wrapper.info = info
        wrapper.clear = clear
        wrapper.load = cache.load
        wrapper.dump = cache.dump
        wrapper.archive = archive
        wrapper.archived = cache.archived
        wrapper.__cache__ = __get_cache
       #wrapper._queue = queue #XXX
        return update_wrapper(wrapper, user_function)

    return decorating_function


def mru_cache(maxsize=100, cache=None, keymap=None, ignore=None, tol=None, deep=False):
    '''most-recently-used (MRU) cache decorator.

    This decorator memoizes a function's return value each time it is called.
    If called later with the same arguments, the cached value is returned, and
    not re-evaluated.  To avoid memory issues, a maximum cache size is imposed.
    For caches with an archive, the full cache dumps to archive upon reaching
    maxsize. For caches without an archive, the MRU algorithm manages the cache.
    This decorator takes an integer tolerance 'tol', equal to the number of
    decimal places to which it will round off floats, and a bool 'deep' for
    whether the rounding on inputs will be 'shallow' or 'deep'.

    maxsize = maximum cache size
    cache = storage hashmap (default is {})
    keymap = cache key encoder (default is keymaps.hashmap(flat=True))
    tol = integer tolerance for rounding (default is None)
    deep = boolean for rounding depth (default is False, i.e. 'shallow')
    ignore = function argument names and indicies to 'ignore' (default is None)

    If *maxsize* is None, this cache will grow without bound.

    If *keymap* is given, it will replace the hashing algorithm for generating
    cache keys.  Several hashing algorithms are available in 'keymaps'. The
    default keymap requires arguments to the cached function to be hashable.

    If the keymap retains type information, then arguments of different types
    will be cached separately.  For example, f(3.0) and f(3) will be treated
    as distinct calls with distinct results.  Cache typing has a memory penalty,
    and may also be ignored by some 'keymaps'.

    If *ignore* is given, the keymap will ignore the arguments with the names
    and/or positional indicies provided. For example, if ignore=(0,), then
    the key generated for f(1,2) will be identical to that of f(3,2) or f(4,2).
    If ignore=('y',), then the key generated for f(x=3,y=4) will be identical
    to that of f(x=3,y=0) or f(x=3,y=10). If ignore=('*','**'), all varargs
    and varkwds will be 'ignored'.  Ignored arguments never trigger a
    recalculation (they only trigger cache lookups), and thus are 'ignored'.
    When caching class methods, it may be useful to ignore=('self',).

    View cache statistics (hit, miss, load, maxsize, size) with f.info().
    Clear the cache and statistics with f.clear().  Replace the cache archive
    with f.archive(obj).  Load from the archive with f.load(), and dump from
    the cache to the archive with f.dump().

    See: http://en.wikipedia.org/wiki/Cache_algorithms#Most_Recently_Used
    '''
    if maxsize == 0:
        return no_cache(cache=cache, keymap=keymep, ignore=ignore, tol=tol, deep=deep)
    if maxsize is None:
        return inf_cache(cache=cache, keymap=keymap, ignore=ignore, tol=tol, deep=deep)

    if keymap is None: keymap = hashmap(flat=True)
    if ignore is None: ignore = tuple()
    if cache is None: cache = archive_dict()
    elif type(cache) is dict: cache = archive_dict(cache)
    # does archive make sense with database, file, ?... (requires more thought)

    if deep: rounded = deep_round
    else: rounded = simple_round
   #else: rounded = shallow_round #FIXME: slow

    @rounded(tol)
    def rounded_args(*args, **kwds):
        return (args, kwds)

    def decorating_function(user_function):
       #cache = dict()                  # mapping of args to results
        queue = deque()                 # order that keys have been used
        stats = [0, 0, 0]               # make statistics updateable non-locally
        HIT, MISS, LOAD = 0, 1, 2       # names for the stats fields
        _len = len                      # localize the global len() function
       #lock = RLock()                  # linkedlist updates aren't threadsafe

        # lookup optimizations (ugly but fast)
        queue_append, queue_popleft = queue.append, queue.popleft
        queue_appendleft, queue_pop = queue.appendleft, queue.pop

        def wrapper(*args, **kwds):
            _args, _kwds = rounded_args(*args, **kwds)
            _args, _kwds = _keygen(user_function, ignore, *_args, **_kwds)
            key = keymap(*_args, **_kwds)

            try:
                # get cache entry
                result = cache[key]
                queue.remove(key)
                stats[HIT] += 1
            except KeyError:
                # if not in cache, look in archive
                if cache.archived():
                    cache.load(key)
                try:
                    result = cache[key]
                    stats[LOAD] += 1
                except KeyError:
                    # if not found, then compute
                    result = user_function(*args, **kwds)
                    cache[key] = result
                    stats[MISS] += 1

                # purge cache
                if _len(cache) > maxsize:
                    if cache.archived():
                        cache.dump()
                        cache.clear() 
                        queue.clear()
                    else: # purge most recently used cache entry
                        del cache[queue_pop()]

            # record recent use of this key
            queue_append(key)
            return result

        def archive(obj):
            """Replace the cache archive"""
            cache.archive = obj

        def __get_cache():
            """Get the cache"""
            return cache

        def clear(keepstats=False):
            """Clear the cache and statistics"""
            cache.clear()
            queue.clear()
            if not keepstats: stats[:] = [0, 0, 0]

        def info():
            """Report cache statistics"""
            return CacheInfo(stats[HIT], stats[MISS], stats[LOAD], maxsize, len(cache))

        # interface
        wrapper.__wrapped__ = user_function
        #XXX: better is handle to key_function=keygen(ignore)(user_function) ?
        wrapper.info = info
        wrapper.clear = clear
        wrapper.load = cache.load
        wrapper.dump = cache.dump
        wrapper.archive = archive
        wrapper.archived = cache.archived
        wrapper.__cache__ = __get_cache
       #wrapper._queue = queue #XXX
        return update_wrapper(wrapper, user_function)

    return decorating_function


def rr_cache(maxsize=100, cache=None, keymap=None, ignore=None, tol=None, deep=False):
    '''random-replacement (RR) cache decorator.

    This decorator memoizes a function's return value each time it is called.
    If called later with the same arguments, the cached value is returned, and
    not re-evaluated.  To avoid memory issues, a maximum cache size is imposed.
    For caches with an archive, the full cache dumps to archive upon reaching
    maxsize. For caches without an archive, the RR algorithm manages the cache.
    This decorator takes an integer tolerance 'tol', equal to the number of
    decimal places to which it will round off floats, and a bool 'deep' for
    whether the rounding on inputs will be 'shallow' or 'deep'.

    maxsize = maximum cache size
    cache = storage hashmap (default is {})
    keymap = cache key encoder (default is keymaps.hashmap(flat=True))
    tol = integer tolerance for rounding (default is None)
    deep = boolean for rounding depth (default is False, i.e. 'shallow')
    ignore = function argument names and indicies to 'ignore' (default is None)

    If *maxsize* is None, this cache will grow without bound.

    If *keymap* is given, it will replace the hashing algorithm for generating
    cache keys.  Several hashing algorithms are available in 'keymaps'. The
    default keymap requires arguments to the cached function to be hashable.

    If the keymap retains type information, then arguments of different types
    will be cached separately.  For example, f(3.0) and f(3) will be treated
    as distinct calls with distinct results.  Cache typing has a memory penalty,
    and may also be ignored by some 'keymaps'.

    If *ignore* is given, the keymap will ignore the arguments with the names
    and/or positional indicies provided. For example, if ignore=(0,), then
    the key generated for f(1,2) will be identical to that of f(3,2) or f(4,2).
    If ignore=('y',), then the key generated for f(x=3,y=4) will be identical
    to that of f(x=3,y=0) or f(x=3,y=10). If ignore=('*','**'), all varargs
    and varkwds will be 'ignored'.  Ignored arguments never trigger a
    recalculation (they only trigger cache lookups), and thus are 'ignored'.
    When caching class methods, it may be useful to ignore=('self',).

    View cache statistics (hit, miss, load, maxsize, size) with f.info().
    Clear the cache and statistics with f.clear().  Replace the cache archive
    with f.archive(obj).  Load from the archive with f.load(), and dump from
    the cache to the archive with f.dump().

    http://en.wikipedia.org/wiki/Cache_algorithms#Random_Replacement
    '''
    if maxsize == 0:
        return no_cache(cache=cache, keymap=keymep, ignore=ignore, tol=tol, deep=deep)
    if maxsize is None:
        return inf_cache(cache=cache, keymap=keymap, ignore=ignore, tol=tol, deep=deep)

    if keymap is None: keymap = hashmap(flat=True)
    if ignore is None: ignore = tuple()
    if cache is None: cache = archive_dict()
    elif type(cache) is dict: cache = archive_dict(cache)
    # does archive make sense with database, file, ?... (requires more thought)

    if deep: rounded = deep_round
    else: rounded = simple_round
   #else: rounded = shallow_round #FIXME: slow

    @rounded(tol)
    def rounded_args(*args, **kwds):
        return (args, kwds)

    def decorating_function(user_function):
       #cache = dict()                  # mapping of args to results
        stats = [0, 0, 0]               # make statistics updateable non-locally
        HIT, MISS, LOAD = 0, 1, 2       # names for the stats fields
        _len = len                      # localize the global len() function
       #lock = RLock()                  # linkedlist updates aren't threadsafe

        def wrapper(*args, **kwds):
            _args, _kwds = rounded_args(*args, **kwds)
            _args, _kwds = _keygen(user_function, ignore, *_args, **_kwds)
            key = keymap(*_args, **_kwds)

            try:
                # get cache entry
                result = cache[key]
                stats[HIT] += 1
            except KeyError:
                # if not in cache, look in archive
                if cache.archived():
                    cache.load(key)
                try:
                    result = cache[key]
                    stats[LOAD] += 1
                except KeyError:
                    # if not found, then compute
                    result = user_function(*args, **kwds)
                    cache[key] = result
                    stats[MISS] += 1

                # purge cache
                if _len(cache) > maxsize:
                    if cache.archived():
                        cache.dump()
                        cache.clear() 
                    else: # purge random cache entry
                        del cache[choice(list(cache.keys()))]
            return result

        def archive(obj):
            """Replace the cache archive"""
            cache.archive = obj

        def __get_cache():
            """Get the cache"""
            return cache

        def clear(keepstats=False):
            """Clear the cache and statistics"""
            cache.clear()
            if not keepstats: stats[:] = [0, 0, 0]

        def info():
            """Report cache statistics"""
            return CacheInfo(stats[HIT], stats[MISS], stats[LOAD], maxsize, len(cache))

        # interface
        wrapper.__wrapped__ = user_function
        #XXX: better is handle to key_function=keygen(ignore)(user_function) ?
        wrapper.info = info
        wrapper.clear = clear
        wrapper.load = cache.load
        wrapper.dump = cache.dump
        wrapper.archive = archive
        wrapper.archived = cache.archived
        wrapper.__cache__ = __get_cache
       #wrapper._queue = None  #XXX
        return update_wrapper(wrapper, user_function)

    return decorating_function


if __name__ == '__main__':
    pass


# EOF
