import os
import threading
import sys
import sickbeard

from sickbeard.webserve import LoginHandler, LogoutHandler, KeyHandler
from sickbeard.webapi import ApiHandler
from sickbeard import logger
from sickbeard.helpers import create_https_certificates, generateApiKey
from tornado.web import Application, StaticFileHandler, RedirectHandler
from tornado.httpserver import HTTPServer
from tornado.ioloop import IOLoop
from tornado.routes import route

class SRWebServer(threading.Thread):
    def __init__(self, options={}, io_loop=None):
        threading.Thread.__init__(self)
        self.daemon = True
        self.alive = True
        self.name = "TORNADO"
        self.io_loop = io_loop or IOLoop.current()

        self.options = options
        self.options.setdefault('port', 8081)
        self.options.setdefault('host', '0.0.0.0')
        self.options.setdefault('log_dir', None)
        self.options.setdefault('username', '')
        self.options.setdefault('password', '')
        self.options.setdefault('web_root', None)
        assert isinstance(self.options['port'], int)
        assert 'data_root' in self.options

        # video root
        if sickbeard.ROOT_DIRS:
            root_dirs = sickbeard.ROOT_DIRS.split('|')
            self.video_root = root_dirs[int(root_dirs[0]) + 1]
        else:
            self.video_root = None

        # web root
        if self.options['web_root']:
            sickbeard.WEB_ROOT = self.options['web_root'] = ('/' + self.options['web_root'].lstrip('/').strip('/'))

        # api root
        if not sickbeard.API_KEY:
            sickbeard.API_KEY = generateApiKey()
        self.options['api_root'] = r'%s/api/%s' % (sickbeard.WEB_ROOT, sickbeard.API_KEY)

        # tornado setup
        self.enable_https = self.options['enable_https']
        self.https_cert = self.options['https_cert']
        self.https_key = self.options['https_key']

        if self.enable_https:
            # If either the HTTPS certificate or key do not exist, make some self-signed ones.
            if not (self.https_cert and os.path.exists(self.https_cert)) or not (
                        self.https_key and os.path.exists(self.https_key)):
                if not create_https_certificates(self.https_cert, self.https_key):
                    logger.log(u"Unable to create CERT/KEY files, disabling HTTPS")
                    sickbeard.ENABLE_HTTPS = False
                    self.enable_https = False

            if not (os.path.exists(self.https_cert) and os.path.exists(self.https_key)):
                logger.log(u"Disabled HTTPS because of missing CERT and KEY files", logger.WARNING)
                sickbeard.ENABLE_HTTPS = False
                self.enable_https = False

        # Load the app
        self.app = Application([],
                                 debug=True,
                                 autoreload=False,
                                 gzip=True,
                                 xheaders=sickbeard.HANDLE_REVERSE_PROXY,
                                 cookie_secret='61oETzKXQAGaYdkL5gEmGeJJFuYh7EQnp2XdTP1o/Vo=',
                                 login_url='/login/',
        )

        # Main Handlers
        self.app.add_handlers('.*$', [
            # webapi handler
            (r'%s(/?.*)' % self.options['api_root'], ApiHandler),

            # webapi key retrieval
            (r'%s/getkey(/?.*)' % self.options['web_root'], KeyHandler),

            # webapi builder redirect
            (r'%s/api/builder' % self.options['web_root'], RedirectHandler, {"url": self.options['web_root'] + '/apibuilder/'}),

            # webui login/logout handlers
            (r'%s/login(/?.*)' % self.options['web_root'], LoginHandler),
            (r'%s/logout(/?.*)' % self.options['web_root'], LogoutHandler),

            # webui redirect
            (r'/', RedirectHandler, {"url": self.options['web_root'] + '/home/'}),

            # webui handlers
        ] + route.get_routes(self.options['web_root']))

        # Static File Handlers
        self.app.add_handlers(".*$", [
            # favicon
            (r'%s/(favicon\.ico)' % self.options['web_root'], StaticFileHandler,
             {"path": os.path.join(self.options['data_root'], 'images/ico/favicon.ico')}),

            # images
            (r'%s/images/(.*)' % self.options['web_root'], StaticFileHandler,
             {"path": os.path.join(self.options['data_root'], 'images')}),

            # cached images
            (r'%s/cache/images/(.*)' % self.options['web_root'], StaticFileHandler,
             {"path": os.path.join(sickbeard.CACHE_DIR, 'images')}),

            # css
            (r'%s/css/(.*)' % self.options['web_root'], StaticFileHandler,
             {"path": os.path.join(self.options['data_root'], 'css')}),

            # javascript
            (r'%s/js/(.*)' % self.options['web_root'], StaticFileHandler,
             {"path": os.path.join(self.options['data_root'], 'js')}),

            # videos
        ] + [(r'%s/videos/(.*)' % self.options['web_root'], StaticFileHandler,
              {"path": self.video_root})])

    def run(self):
        if self.enable_https:
            protocol = "https"
            self.server = HTTPServer(self.app, ssl_options={"certfile": self.https_cert, "keyfile": self.https_key})
        else:
            protocol = "http"
            self.server = HTTPServer(self.app)

        logger.log(u"Starting SickRage on " + protocol + "://" + str(self.options['host']) + ":" + str(
            self.options['port']) + "/")

        try:
            self.server.listen(self.options['port'], self.options['host'])
        except:
            etype, evalue, etb = sys.exc_info()
            logger.log(
                "Could not start webserver on %s. Excpeption: %s, Error: %s" % (self.options['port'], etype, evalue),
                logger.ERROR)
            return

        try:
            self.io_loop.start()
            self.io_loop.close(True)
        except (IOError, ValueError):
            # Ignore errors like "ValueError: I/O operation on closed kqueue fd". These might be thrown during a reload.
            pass

    def shutDown(self):
        self.alive = False
        self.io_loop.stop()