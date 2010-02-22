# trying to chdir() to dirname($0)
import os
if os.environ['USER'] != "root":
	raise Exception, "OvzCP must be run as root"
try:
	os.chdir(os.path.dirname(__file__))
except OSError:
	pass
# looking up tornado, the webserver
# otherwise put our egg into sys.path
try:
	import tornado #not really used
except ImportError:
	import sys
	sys.path.append(os.path.join(os.getcwd(), "tornado-0.2-py2.5-linux-i686.egg"))
try:
	import jinja2
except ImportError:
	import sys
	sys.path.append(os.path.join(os.getcwd(), "Jinja2-2.3-py2.5.egg"))
	import jinja2
import ConfigParser, cPickle, openvz
import tornado.httpserver
import tornado.ioloop
import tornado.web
import tornado.auth

# parse config
_config = ConfigParser.SafeConfigParser()
_config.read("config.ini")

class BaseHandler(tornado.web.RequestHandler):
	def get_current_user(self):
		data = self.get_user()
		if data:
			return data['email']
	def get_user(self):
		data = self.get_secure_cookie("auth")
		if data:
			return cPickle.loads(data)
	def render(self, tmpl, *args, **kwargs):
		jinja = jinja2.Environment(loader=jinja2.loaders.FileSystemLoader("template"))
		self.write(jinja.get_template(tmpl).render(current_user=self.current_user, *args, **kwargs))
		return

class MainHandler(BaseHandler):
	@tornado.web.authenticated
	def get(self):
		self.render("index.html")

class Containers(BaseHandler):
	@tornado.web.authenticated
	def get(self):
		self.render("container.html", container=openvz.list(), title="Containers")

class RestartVM(BaseHandler):
	@tornado.web.authenticated
	def get(self):
		vm = openvz.VM(self.get_argument("veid"))
		if not vm.running:
			self.redirect("/containers")
			return False
		proc = vm.restart()
		proc.wait()
		self.render("container.html", container=openvz.list(), title="Containers", message="<pre>"+proc.stdout.read()+"</pre>")

class StopVM(BaseHandler):
	@tornado.web.authenticated
	def get(self):
		vm = openvz.VM(self.get_argument("veid"))
		if not vm.running:
			self.redirect("/containers")
			return False
		proc = vm.stop()
		proc.wait()
		self.render("container.html", container=openvz.list(), title="Containers", message="<pre>"+proc.stdout.read()+"</pre>")

class StartVM(BaseHandler):
	@tornado.web.authenticated
	def get(self):
		vm = openvz.VM(self.get_argument("veid"))
		if vm.running:
			self.redirect("/containers")
			return False
		proc = vm.start()
		proc.wait()
		self.render("container.html", container=openvz.list(), title="Containers", message="<pre>"+proc.stdout.read()+"</pre>")

class GoogleHandler(BaseHandler, tornado.auth.GoogleMixin):
	@tornado.web.asynchronous
	def get(self):
		self.next = self.get_argument("next", "/")
		if self.next == "/auth":
			self.next = "/"
		if self.get_argument("openid.mode", None):
			self.get_authenticated_user(self.async_callback(self._on_auth))
			return
		self.authenticate_redirect()
	def _on_auth(self, user):
		if not user:
			self.authenticate_redirect()
			return
		self.set_secure_cookie("auth", cPickle.dumps(user))
		self.redirect(self.next)

settings = {
	"cookie_secret": _config.get("auth", "secret"),
	"login_url": "/auth",
	"xsrf_cookies": True,
	"static_path": "static",
}

application = tornado.web.Application([
	(r"/", MainHandler),
	(r"/auth", GoogleHandler),
	(r"/containers", Containers),
	(r"/restart", RestartVM),
	(r"/stop", StopVM),
	(r"/start", StartVM),
], **settings)

if __name__ == "__main__":
	http_server = tornado.httpserver.HTTPServer(application)
	http_server.listen(21212)
	tornado.ioloop.IOLoop.instance().start()
