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
import models
import ConfigParser, cPickle, openvz
import tornado.httpserver
import tornado.ioloop
import tornado.web
import tornado.auth

# parse config
_config = ConfigParser.SafeConfigParser()
_config.read("config.ini")

def myVM(user):
	return models.VM.select(models.OR(models.VM.q.owner == user, models.VM.q.owner == None))

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
		# sync the vm list
		for i in openvz.listVM():
			if not models.VM.select(models.VM.q.veid == i.veid).count():
				models.VM(veid=i.veid)
		errmsg = ""
		txtmsg = ""
		if self.get_argument("error", None):
			err = self.get_argument("error")
			if err == "1":
				errmsg = "VM not owned by current user"
			elif err == "2":
				errmsg = "VM is not running"
			elif err == "3":
				errmsg = "VM is already owned by current user"
		if self.get_argument("msg", None):
			msg = self.get_argument("msg")
			if msg == "1":
				txtmsg = "VM now belongs to you"
			elif msg == "2":
				txtmsg = "VM ownership removed. Other can now claim this VM"
		self.render("container.html", container=myVM(self.current_user),
			title="Containers", error=errmsg, msg=txtmsg)

class RestartVM(BaseHandler):
	@tornado.web.authenticated
	def get(self):
		sql = models.VM.select(models.VM.q.veid == int(self.get_argument("veid")))[0]
		if sql.owner != self.current_user and sql.owner:
			self.redirect("/containers?error=1")
			return
		vm = sql.vz
		if not vm.running:
			self.redirect("/containers?error=2")
			return
		proc = vm.restart()
		proc.wait()
		self.render("container.html", container=myVM(self.current_user), title="Containers", message="<pre>"+proc.stdout.read()+"</pre>")

class StopVM(BaseHandler):
	@tornado.web.authenticated
	def get(self):
		sql = models.VM.select(models.VM.q.veid == int(self.get_argument("veid")))[0]
		if sql.owner != self.current_user and sql.owner:
			self.redirect("/containers?error=1")
			return
		vm = sql.vz
		if not vm.running:
			self.redirect("/containers?error=2")
			return
		proc = vm.stop()
		proc.wait()
		self.render("container.html", container=myVM(self.current_user), title="Containers", message="<pre>"+proc.stdout.read()+"</pre>")

class StartVM(BaseHandler):
	@tornado.web.authenticated
	def get(self):
		sql = models.VM.select(models.VM.q.veid == int(self.get_argument("veid")))[0]
		if sql.owner != self.current_user and sql.owner:
			self.redirect("/containers?error=1")
			return
		vm = sql.vz
		if vm.running:
			self.redirect("/containers?error=2")
			return
		proc = vm.start()
		proc.wait()
		self.render("container.html", container=myVM(self.current_user), title="Containers", message="<pre>"+proc.stdout.read()+"</pre>")

class ClaimVM(BaseHandler):
	@tornado.web.authenticated
	def get(self):
		sql = models.VM.select(models.VM.q.veid == int(self.get_argument("veid")))[0]
		if not self.get_argument("revert", False):
			if sql.owner:
				self.redirect("/containers?error=1")
				return
			if sql.owner == self.current_user:
				self.redirect("/containers?error=3")
				return
			sql.set(owner=self.current_user)
		else:
			if not sql.owner:
				self.redirect("/containers?error=1")
				return
			if sql.owner != self.current_user:
				self.redirect("/containers?error=1")
				return
			sql.set(owner=None)
		self.redirect("/containers?msg=2")

class VMinfo(BaseHandler):
	@tornado.web.authenticated
	def get(self, veid):
		sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		if sql.owner != self.current_user and sql.owner:
			self.redirect("/containers?error=1")
			return
		self.render("info.html", veid=veid, vm=sql.vz)

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
	(r"/claim", ClaimVM),
	(r"/vm/([0-9]+)", VMinfo),
], **settings)

if __name__ == "__main__":
	http_server = tornado.httpserver.HTTPServer(application)
	http_server.listen(21212)
	tornado.ioloop.IOLoop.instance().start()
