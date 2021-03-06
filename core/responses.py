import sublime

import re
from concurrent import futures
from collections import namedtuple, deque

import requests

from .parsers import PREFIX


Request_ = namedtuple('Request', 'request, method, url, args, kwargs, ordering, session')
Response = namedtuple('Response', 'req, res, err')

methods = {
    'GET': requests.get,
    'OPTIONS': requests.options,
    'HEAD': requests.head,
    'POST': requests.post,
    'PUT': requests.put,
    'PATCH': requests.patch,
    'DELETE': requests.delete,
}


class Request(Request_):
    """Hashable `Request` namedtuple.
    """
    def __hash__(self):
        return hash(self.ordering)

    def __eq__(self, other):
        return self.ordering == other.ordering

    def __ne__(self, other):
        return not(self == other)


def parse_args(*args, **kwargs):
    """Used in conjunction with eval to parse args and kwargs from a string.
    """
    return args, kwargs


class ResponseThreadPool:
    """Allows requests to be invoked concurrently, and allows client code to
    inspect instance's responses as they are returned.
    """
    def get_response(self, request, ordering):
        """Calls request with specified args and kwargs parsed from request
        string.

        Also sets "Response" key in env to `Response` object, to provide true
        "chaining" of requests. If two requests are run serially, the second
        request can reference the response returned by the previous request.
        """
        if isinstance(request, Request):  # no need to prepare request
            req = request._replace(ordering=ordering)
        else:
            req = prepare_request(request, self.env, ordering)
        self.pending_requests.add(req)

        res, err = None, ''
        if self.is_done:  # prevents further requests from being made if pool is cancelled
            return Response(req, res, err)  # check using: https://requestb.in/

        try:
            if req.session:
                session = self.env.get(req.session)
                if isinstance(session, requests.sessions.Session):
                    res = getattr(session, req.method.lower())(*req.args, **req.kwargs)
                else:
                    err = 'Session Error: there is no session `{}` defined in your environment'.format(req.session)
            else:
                res = methods.get(req.method)(*req.args, **req.kwargs)
        except requests.Timeout:
            err = 'Timeout Error: the request timed out'
        except requests.ConnectionError:
            err = 'Connection Error: check your connection'
        except SyntaxError as e:
            err = '{}: {}\n\n{}'.format('Syntax Error', e,
                                        'Run "Requester: Show Syntax" to review properly formatted requests')
        except TypeError as e:
            err = '{}: {}'.format('Type Error', e)
        except Exception as e:
            err = '{}: {}'.format('Other Error', e)

        self.env['Response'] = res  # to allow "chaining" of serially executed requests
        return Response(req, res, err)

    def __init__(self, requests, env, max_workers):
        self.is_done = False
        self.responses = deque()
        self.requests = requests
        self.pending_requests = set()
        self.env = env
        self.max_workers = max_workers

    def get_pending_requests(self):
        """Getter for `self.pending_requests`. This is a `set` that's shared
        between threads, which makes iterating over it unsafe.
        """
        return self.pending_requests.copy()

    def run(self):
        """Concurrently invoke `get_response` for all of instance's `requests`.
        """
        with futures.ThreadPoolExecutor(
            max_workers=min(self.max_workers, len(self.requests))
        ) as executor:
            to_do = []
            for i, request in enumerate(self.requests):
                future = executor.submit(self.get_response, request, i)
                to_do.append(future)

            for future in futures.as_completed(to_do):
                result = future.result()
                # `responses` and `pending_requests` are instance properties, which means
                # client code can inspect instance to read responses as they are completed
                try:
                    self.pending_requests.remove(result.req)
                except KeyError:
                    print('{} was not in pending requests, this is weird...'.format(result.req))
                self.responses.append(result)
        self.is_done = True


def prepare_request(request, env, ordering):
    """Parse and evaluate args and kwargs in request string under context of
    env.

    Also, prepare request string: if request is not prefixed with "{var_name}.",
    prefix request with "requests." Accepts a request string and returns a
    `Request` instance.

    Finally, ensure request can time out so it doesn't hang indefinitely.
    http://docs.python-requests.org/en/master/user/advanced/#timeouts
    """
    req = request.strip()
    if not re.match(PREFIX, req):
        req = 'requests.' + req
    session = None
    if not req.startswith('requests.'):
        session = req.split('.')[0]

    env['__parse_args__'] = parse_args
    index = req.index('(')
    try:
        args, kwargs = eval('__parse_args__{}'.format(req[index:]), env)
    except:
        args, kwargs = [], {}
    else:
        args = list(args)

    method = req[:index].split('.')[1].strip().upper()
    url = kwargs.get('url', None)
    if url is not None:
        url = prepare_url(url)
        kwargs['url'] = url
    else:
        try:
            url = args[0]
        except:
            pass  # this method isn't responsible for raising exceptions
        else:
            url = prepare_url(url)
            args[0] = url

    if 'timeout' not in kwargs:
        kwargs['timeout'] = sublime.load_settings('Requester.sublime-settings').get('timeout', None)
    return Request(req, method, url, args, kwargs, ordering, session)


def prepare_url(url):
    """Prepend scheme to URL if necessary.
    """
    if type(url) is str and len(url.split('://')) == 1:
        return 'http://' + url
    return url
