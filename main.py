#!/usr/bin/python
# -*- encoding: utf-8
from __future__ import division

# trying to chdir() to dirname($0)
import os
if os.environ['USER'] != "root":
	raise Exception, "OvzCP must be run as root"
try:
	os.chdir(os.path.dirname(__file__))
except OSError:
	pass

import sys
sys.path.insert(0, os.path.join(os.getcwd(), "tornado-0.2-py2.5-linux-i686.egg"))
# Debian lenny's Jinja2 is older than 2.2 thus cannot be used
sys.path.insert(0, os.path.join(os.getcwd(), "Jinja2-2.3-py2.5.egg"))
sys.path.append(os.path.join(os.getcwd(), "netifaces-0.5-py2.5-linux-i686.egg"))

import models
import ConfigParser, cPickle, openvz, math, time, re, jinja2, netifaces, babel, gettext
import tornado.httpserver
import tornado.ioloop
import tornado.web
import tornado.auth

# parse config
_config = ConfigParser.SafeConfigParser()
_config.read("config.ini")

def xsrf_check(func):
	def f(self, *args, **kwargs):
		try:
			if self.get_cookie("_xsrf") != self.get_argument("_xsrf"):
				self.write(_("XSRF Check fail"))
				return False
		except Exception, e:
			self.write(_("XSRF Check fail by exception"))
			return False
		return func(self, *args, **kwargs)
	return f

def myVM(user, ownerOnly=False):
	if ownerOnly:
		return user.vm
	else:
		return models.VM.select(models.OR(models.VM.q.user == user, models.VM.q.user == None))
def vmBilling(vm, desc=False, user=False):
	prices = {}
	# perVM
	prices['perVM'] = _config.getint("billing", "perVM")
	# memory
	prices['memory'] = int(math.ceil((_config.getint("billing", "memory")/_config.getint("billing", "memoryPer"))*(vm.memlimit[0]/1000000)))
	# disk
	diskusage = (vm.diskinfo[0]/1000)
	if vm.running:
		if vm.diskinfo[1] > vm.diskinfo[0]:
			diskusage = (vm.diskinfo[1]/1000)
	prices['disk'] = int(math.ceil((_config.getint("billing", "disk")/_config.getint("billing", "diskPer"))*diskusage))
	# sum
	prices['total'] = reduce(lambda x,y: x+y, prices.values())
	if user:
		prices['time'] = (user.credit / prices['total'])*60
	if desc:
		return prices
	else:
		return prices['total']

class BaseHandler(tornado.web.RequestHandler):
	def get_current_user(self):
		data = self.get_user()
		if data:
			return data
	def get_user_locale(self):
		out = None
		if self.get_argument("_locale", None):
			out = self.get_argument("_locale")
			self.set_cookie("locale", out)
		if not out:
			out=self.get_cookie("locale", None)
		if out:
			return [out]
		else:
			return None
	def get_user(self):
		data = self.get_secure_cookie("auth")
		if data:
			userData = cPickle.loads(data)
			query = models.User.select(models.User.q.email == userData['email'])
			if query.count():
				return query[0]
			else:
				return models.User(email=userData['email'], credit=0)
	def prepare(self):
		self.gettext = gettext.translation('messages', os.path.join(os.getcwd(), "po"), self.get_user_locale(), fallback=True)
		self.gettext.install(True)
	def render(self, tmpl, *args, **kwargs):
		totalcost = 0
		for i in myVM(self.current_user, True):
			if i.vz.running:
				totalcost += vmBilling(i.vz)
		
		jinja = jinja2.Environment(loader=jinja2.loaders.FileSystemLoader("template"), extensions=['jinja2.ext.i18n'])
		jinja.install_gettext_translations(self.gettext)
		self.write(jinja.get_template(tmpl).render(current_user=self.current_user, static_url=self.static_url,
			xsrf_form_html=self.xsrf_form_html, xsrf=self.get_cookie("_xsrf"), request=self.request, config=_config, totalcost=totalcost, 
			str=str, locale=self.locale, *args, **kwargs))
		return

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
				# NOTE: When accessing /vm/<veid> but OvzCP detect that the VM is not belongs to the current user, it will return this error
				errmsg = _("VM not owned by current user")
			elif err == "2":
				errmsg = _("VM is not running")
			elif err == "3":
				# NOTE: Displayed when trying to claim a VM that belongs to yourself
				errmsg = _("VM is already owned by current user")
			elif err == "4":
				# NOTE: Displayed when trying to start a VM but user's credit is lower than 1,000 credits. The %s is the unit name such as credit
				errmsg = _("%s is under 1,000, please refill.") % _config.get("billing", "unit")
			elif err == "5":
				errmsg = _("VM is running")
			elif err == "6":
				# NOTE: Displayed when trying to create a VM but user's credit is lower than 5,000 credits. The %s is the unit name such as credit
				errmsg = _("You need 5,000 %s to create a VM." % _config.get("billing", "unit"))
		if self.get_argument("msg", None):
			msg = self.get_argument("msg")
			if msg == "1":
				txtmsg = _("VM now belongs to you")
			elif msg == "2":
				txtmsg = _("VM ownership removed. Other can now claim this VM")
			elif msg == "3":
				txtmsg = _("VM destroyed")
		self.render("container.html", container=myVM(self.current_user),
			title=_("Containers"), error=errmsg, message=txtmsg)

class HostSpec(BaseHandler):
	@tornado.web.authenticated
	def get(self):
		import commands, re
		# copied from openvz.VM.meminfo
		d = open("/proc/meminfo").read().strip()
		out= {}
		for i in d.split("\n"):
			i = re.split(":[ ]+", i)
			if i[1].endswith(" kB"):
				i[1] = int(i[1].split(" ")[0])*1024
			out[i[0]] = i[1]
		mem=out.copy()
		# copied from openvz.VM.diskinfo
		d = commands.getoutput("df")
		d = re.split(" [ ]+", d.split("\n")[1])
		disk = [int(d[1])*1000, int(d[2])*1000, int(d[3])*1000]
		# copied from openvz.VM.loadAvg
		d = open("/proc/loadavg").read()
		loadAvg= map(lambda x:float(x), d.split(" ")[:3])
		# copied from openvz.VM.uptime
		uptime = float(open("/proc/uptime").read().split(" ")[0])
		dist = commands.getoutput("lsb_release -a|grep Description").split("\n")[1].split("\t")[1]
		kernel = commands.getoutput("uname -a")
		nproc = commands.getoutput('ps ax | wc -l | tr -d " "')
		runningVM = len(filter(lambda x: x.running,openvz.listVM()))
		cpu = commands.getoutput('cat /proc/cpuinfo |grep "model name"').split("\n")[0].split("\t")[1][2:]
		hostname = open("/etc/hostname").read().strip()
		self.render("spec.html", mem=mem, disk=disk, loadAvg=loadAvg, os=dist, uptime=uptime, kernel=kernel, nproc=nproc,
			runningVM=runningVM, cpu=cpu, hostname=hostname, title=_("Host OS specification"))

class CreateVM(BaseHandler):
	@tornado.web.authenticated
	def get(self):
		if self.current_user.credit < 5000:
			self.redirect("/?error=6")
			return
		hostnames = map(lambda x: x.hostname,openvz.listVM())
		err=""
		if self.get_argument("error", None):
			e = self.get_argument("error")
			if e == "1":
				err=_("Terms of Service not accepted")
			elif e == "2":
				err=_("Invalid template name")
			elif e == "3":
				err=_("Passwords do not match")
			elif e == "4":
				err=_("Invalid hostname")
		self.render("create.html", templates=openvz.listTemplates(), hostnames = hostnames,
			title=_("Creating VM"), error=err)
	def post(self):
		if self.current_user.credit < 5000:
			self.redirect("/?error=6")
			return
		if not self.get_argument("tos"):
			self.redirect("/create?error=1")
			return
		if self.get_argument("os") not in openvz.listTemplates():
			self.redirect("/create?error=2")
			return
		if self.get_argument("root") != self.get_argument("root2"):
			self.redirect("/create?error=3")
			return
		hostnames = map(lambda x: x.hostname,openvz.listVM())
		if not re.match("^([0-9A-Za-z_\-]+)$", self.get_argument("hostname")) or self.get_argument("hostname") in hostnames:
			self.redirect("/create?error=4")
			return
		vm=openvz.createVM(self.get_argument("os"), None, _config.get("iface", "nameserver"), self.get_argument("root"))
		models.VM(veid=vm.veid, user=self.current_user)
		# hostname
		vm.hostname = self.get_argument("hostname")
		# ram
		ram = float(self.get_argument("ram"))
		burst = math.floor(ram+(ram*int(_config.get("billing", "memoryBurst"))/100))
		memlimit = [ram, burst, burst+10240]
		vm.memlimit = memlimit
		# disk
		vm.diskinfo = float(self.get_argument("disk"))
		# add IP
		vm.ip = _config.get("iface", "vmIP")+str(vm.veid)
		self.redirect("/vm/"+str(vm.veid))

class DestroyVM(BaseHandler):
	@tornado.web.authenticated
	@xsrf_check
	def get(self, veid):
		vm = openvz.VM(int(veid))
		self.render("destroy.html", veid=veid, hostname=vm.hostname, credit=vmBilling(vm), title=_("Destroy %s")%veid)
	def post(self, veid):
		sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		if sql.user != self.current_user and sql.user:
			self.redirect("/?error=1")
			return
		vm = sql.vz
		if vm.running:
			self.redirect("/?error=5")
			return
		proc = vm.destroy()
		proc.wait()
		sql.destroySelf()
		self.redirect(self.get_argument("return", "/?msg=3"))

class RestartVM(BaseHandler):
	@tornado.web.authenticated
	@xsrf_check
	def get(self, veid):
		sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		if sql.user != self.current_user and sql.user:
			self.redirect("/?error=1")
			return
		vm = sql.vz
		if not vm.running:
			self.redirect("/?error=2")
			return
		proc = vm.restart()
		proc.wait()
		self.redirect(self.get_argument("return", "/vm/"+str(veid)))

class StopVM(BaseHandler):
	@tornado.web.authenticated
	@xsrf_check
	def get(self, veid):
		sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		if sql.user != self.current_user and sql.user:
			self.redirect("/?error=1")
			return
		vm = sql.vz
		if not vm.running:
			self.redirect("/?error=2")
			return
		proc = vm.stop()
		proc.wait()
		self.redirect(self.get_argument("return", "/vm/"+str(veid)))

class StartVM(BaseHandler):
	@tornado.web.authenticated
	@xsrf_check
	def get(self, veid):
		if self.current_user.credit < 1000:
			self.redirect("/?error=4")
			return
		sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		if sql.user != self.current_user and sql.user:
			self.redirect("/?error=1")
			return
		vm = sql.vz
		if vm.running:
			self.redirect("/?error=2")
			return
		proc = vm.start()
		proc.wait()
		# Sometimes OvzCP return internal server error
		# this should remedy the bug
		time.sleep(2)
		self.redirect(self.get_argument("return", "/vm/"+str(veid)))

class ClaimVM(BaseHandler):
	@tornado.web.authenticated
	def get(self, veid):
		sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		if not self.get_argument("revert", False):
			if sql.user:
				self.redirect("/?error=1")
				return
			if sql.user == self.current_user:
				self.redirect("/?error=3")
				return
			sql.set(user=self.current_user)
		else:
			return
			if not sql.user:
				self.redirect("/?error=1")
				return
			if sql.user != self.current_user:
				self.redirect("/?error=1")
				return
			sql.set(user=None)
		self.redirect(self.get_argument("return", "/vm/"+str(veid)))

class VMinfo(BaseHandler):
	@tornado.web.authenticated
	def get(self, veid):
		try:
			sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		except IndexError:
			self.redirect("/?error=1")
			return
		if sql.user != self.current_user and sql.user:
			self.redirect("/?error=1")
			return
		errmsg = ""
		txtmsg = ""
		if sql.vz.diskinfo[1] > sql.vz.diskinfo[0]:
			errmsg=_("VM disk usage exceed allocated amount. You will be billed by amount used instead")
		if self.get_argument("error", None):
			err = self.get_argument("error")
			if err == "1":
				# NOTE: Duplicate entry
				errmsg = _("Entry already exists")
			elif err == "2":
				restart = (int(self.get_secure_cookie("varnishrestart"))+300) - time.time()
				# NOTE: <span class='time'>%s</span> is time in this format: 1 day 3 hours 4 minutes 5 seconds
				errmsg = _("You have to wait <span class='time'>%s</span> before you can restart the reverse proxy again")%restart
			elif err == "3":
				# NOTE: Malformat hostname
				errmsg = _("Invalid hostname")
			elif err == "4":
				# NOTE: Network interface
				errmsg = _("Invalid interface")
			elif err == "5":
				errmsg = _("Passwords do not match")
		if self.get_argument("message", None):
			msg = self.get_argument("message")
			if msg == "1":
				txtmsg = _("Settings commited.")
			elif msg == "2":
				txtmsg = _("No changes.")
			elif msg == "3":
				txtmsg = _("Root password successfully changed")
		interface={}
		for iface in netifaces.interfaces():
			if not re.match(_config.get("iface", "allowed"), iface):
				continue
			try:
				if _config.get("ifaceuser", iface.replace(":", "-")) != self.current_user.email:
					continue
			except ConfigParser.NoOptionError:
				pass
			owned = False
			if models.PortForward.select(models.AND(models.PortForward.q.iface == iface, models.PortForward.q.outport == -1)).count():
				owned = True
			try:
				interface[iface] = [netifaces.ifaddresses(iface)[netifaces.AF_INET][0]['addr'], owned]
			except KeyError, e:
				pass
		self.render("info.html", veid=veid, vz=sql.vz, vm=sql, title=_("%s information")%veid, billing=vmBilling(sql.vz, True, self.current_user),
			error=errmsg, message=txtmsg, interface=interface)

class VMedit(BaseHandler):
	@tornado.web.authenticated
	def get(self, veid):
		try:
			sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		except IndexError:
			self.redirect("/?error=1")
			return
		if sql.user != self.current_user and sql.user:
			self.redirect("/?error=1")
			return
		errmsg = ""
		txtmsg = ""
		if self.get_argument("error", None):
			pass
		hostnames = map(lambda x: x.hostname, filter(lambda x: x.veid != int(veid),openvz.listVM()))
		self.render("edit.html", veid=veid, vz=sql.vz, title=_("Edit %s")%veid, error=errmsg, message=txtmsg, hostnames=hostnames)
	@tornado.web.authenticated
	def post(self, veid):
		try:
			sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		except IndexError:
			self.redirect("/?error=1")
			return
		if sql.user != self.current_user and sql.user:
			self.redirect("/?error=1")
			return
		hostnames = map(lambda x: x.hostname,openvz.listVM())
		if self.get_argument("hostname") in hostnames:
			self.redirect("/vm/"+veid+"?error=3")
			return
		change = []
		# Hostname change
		if self.get_argument("hostname") != sql.vz.hostname:
			sql.vz.hostname = self.get_argument("hostname")
			change.append("hostname")
		# Disk space change
		if int(float(self.get_argument("disk"))) != sql.vz.diskinfo[0]:
			sql.vz.diskinfo = float(self.get_argument("disk"))
			change.append("disk")
		# Memory change
		if int(float(self.get_argument("ram"))) != sql.vz.memlimit[0]:
			ram = float(self.get_argument("ram"))
			burst = math.floor(ram+(ram*int(_config.get("billing", "memoryBurst"))/100))
			memlimit = [ram, burst, burst+10240]
			sql.vz.memlimit = memlimit
			change.append("memlimit")
		if change:
			sql.vz.restart().wait()
			self.redirect("/vm/"+str(veid)+"?message=1")
		else:
			self.redirect("/vm/"+str(veid)+"?message=2")

class Billing(BaseHandler):
	@tornado.web.authenticated
	def get(self):
		# sync the vm list
		for i in openvz.listVM():
			if not models.VM.select(models.VM.q.veid == i.veid).count():
				models.VM(veid=i.veid)
		vmcost = []
		for i in myVM(self.current_user, True):
			if i.vz.running:
				vmcost.append((i.veid, vmBilling(i.vz)))
		self.render("billing.html", vmcost=vmcost, title=_("Billing"))

class PayReceive(BaseHandler):
	def check_xsrf_cookie(self):
		""" Bypass XSRF check """
		return
	@tornado.web.authenticated
	def post(self):
		self.write(self.request.arguments)

class RootPW(BaseHandler):
	@tornado.web.authenticated
	def post(self, veid):
		sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		if sql.user != self.current_user or not sql.user:
			self.redirect("/?error=1")
			return
		if self.get_argument("root") != self.get_argument("root2"):
			self.redirect("/vm/"+str(veid)+"?error=5")
			return
		sql.vz.root_password(self.get_argument("root"))
		self.redirect("/vm/"+str(veid)+"?message=3")

class AddPort(BaseHandler):
	@tornado.web.authenticated
	@xsrf_check
	def get(self, veid):
		if not _config.getboolean("iface", "enabled"): return
		d=models.PortForward.select(models.PortForward.q.id == int(self.get_argument("delete")))[0]
		if d.vm.user != self.current_user or not d.vm.user:
			self.redirect("/?error=1")
			return
		d.destroySelf()
		import vmfw
		vmfw.update(models.PortForward.select())
		vmfw.restart()
		self.redirect("/vm/%s#portedit"%veid)
	@tornado.web.authenticated
	def post(self, veid):
		if not _config.getboolean("iface", "enabled"): return
		sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		if sql.user != self.current_user or not sql.user:
			self.redirect("/?error=1")
			return
		if not re.match(_config.get("iface", "allowed"), self.get_argument("iface")):
			self.redirect("/vm/%s?error=4"%veid)
			return
		try:
			if _config.get("ifaceuser", self.get_argument("iface").replace(":", "-")) != self.current_user.email:
				self.redirect("/vm/%s?error=4"%veid)
				return
		except ConfigParser.NoOptionError:
			pass
		if self.get_argument("outport").lower() == "dmz":
			outport = -1
			inport = -1
		else:
			outport = int(self.get_argument("outport")) 
			inport = int(self.get_argument("port"))
		if models.PortForward.select(models.AND(models.PortForward.q.iface==self.get_argument("iface"), 
				models.OR(models.PortForward.q.outport==outport, models.PortForward.q.outport==-1))).count():
			self.redirect("/vm/%s?error=1"%veid)
			return
		models.PortForward(vm=sql, iface=self.get_argument("iface"), port=inport, outport=outport)
		import vmfw
		vmfw.update(models.PortForward.select())
		vmfw.restart()
		self.redirect("/vm/%s#portedit"%veid)

class AddVarnish(BaseHandler):
	@tornado.web.authenticated
	@xsrf_check
	def get(self, veid):
		if not _config.getboolean("varnish", "enabled"): return
		d=models.VarnishCond.select(models.VarnishCond.q.id == int(self.get_argument("delete")))[0]
		if d.backend.vm.user != self.current_user or not d.backend.vm.user:
			self.redirect("/?error=1")
			return
		# check for orphaned backend
		backend = d.backend
		d.destroySelf()
		varnish.updateRecv(models.VarnishCond.select())
		import varnish
		if backend.cond.count() == 0:
			backend.destroySelf()
			varnish.updateBackend(models.VarnishBackend.select())
		self.redirect("/vm/%s#webedit"%veid)
	@tornado.web.authenticated
	def post(self, veid):
		if not _config.getboolean("varnish", "enabled"): return
		sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		if sql.user != self.current_user or not sql.user:
			self.redirect("/?error=1")
			return
		if not re.match(r"^[a-zA-Z0-9\.\-_]+$", self.get_argument("host")):
			self.redirect("/vm/%s?error=3"%veid)
			return
		if models.VarnishCond.select(models.VarnishCond.q.hostname==self.get_argument("host")).count():
			self.redirect("/vm/%s?error=1"%veid)
			return
		backend = models.VarnishBackend.select(models.AND(models.VarnishBackend.q.port == int(self.get_argument("port")), models.VarnishBackend.q.vm==sql))
		if backend.count():
			backend = backend[0]
		else:
			backend = models.VarnishBackend(name=sql.vz.hostname+str(self.get_argument("port")), vm=sql, port=int(self.get_argument("port")))
			backendUpdate=True
		models.VarnishCond(hostname=self.get_argument("host"), subdomain=bool(self.get_argument("subdomain", False)), varnishBackend=backend)
		import varnish
		if backendUpdate:
			varnish.updateBackend(models.VarnishBackend.select())
		varnish.updateRecv(models.VarnishCond.select())
		self.redirect("/vm/%s#webedit"%veid)

class Munin(BaseHandler):
	def post(self, veid):
		if not _config.getboolean("munin", "enabled"): return
		sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		if sql.user != self.current_user or not sql.user:
			self.write(`{"error": _("VM not owned by current user")}`.replace("'", '"'))
			return
		if self.get_argument("status") == "toggle":
			e = not sql.munin
		else:
			e = self.get_argument("status") == "true"
		import munin
		if e:
			if not munin.check_ip(sql.vz.ip):
				self.write(`{"error": _("Cannot connect to Munin on the VM.")}`.replace("'", '"'))
				return
			models.Munin(vm=sql)
		else:
			sql.munin.destroySelf()
		self.write((`{"status": bool(sql.munin)}`).lower().replace("'", '"'))

class VarnishRestart(BaseHandler):
	@tornado.web.authenticated
	@xsrf_check
	def get(self):
		if not _config.getboolean("varnish", "enabled"): return
		if self.get_argument("state") == "0":
			cookie = self.get_secure_cookie("varnishrestart")
			if not cookie:
				cookie=1
			if (int(cookie)+300) - time.time() > 0:
				#self.redirect("/vm/%s?error=2"%self.get_argument("veid"))
				self.write(_("Limit not reached. Please wait %s seconds") % (int(cookie)+300) - time.time())
				return
			self.set_secure_cookie("varnishrestart", str(int(time.time())))
			self.set_secure_cookie("varnishcookie", str(int(time.time())))
		else:
			t = int(self.get_secure_cookie("varnishcookie"))
			if time.time()-t > 3:
				return
			import varnish
			varnish.restart()
			
class Dashboard(BaseHandler):
	def check_xsrf_cookie(self):
		""" Bypass XSRF check """
		return
	@tornado.web.authenticated
	def get(self):
		myvm = myVM(self.current_user, True)
		billing = 0
		for i in myvm:
			if i.vz.running:
				billing += vmBilling(i.vz)
		self.render("dashboard.html", title=_("Dashboard"), container=myvm, billing=billing)
	def post(self):
		data = self.get_argument("data")
		if data == "vmload":
			out = {}
			for i in myVM(self.current_user, True):
				if i.vz.running:
					out[i.vz.hostname] = i.vz.loadAvg[0]
			d = open("/proc/loadavg").read()
			loadAvg= map(lambda x:float(x), d.split(" ")[:3])
			out['Host OS'] = loadAvg[0]
			self.write((`[out]`).replace("'", '"'))

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

class CronRun(BaseHandler):
	def get(self):
		if self.get_argument("cron_key") != _config.get("auth", "cron_key"):
			return
		proclist = []
		for u in models.User.select():
			totalcost = 0
			for i in myVM(u, True):
				if i.vz.running:
					totalcost += vmBilling(i.vz)
			u.credit -= totalcost
			if u.credit <= 0:
				for i in myVM(u, True):
					if i.vz.running:
						proclist.append(i.vz.stop())
		for i in proclist:
			i.wait()
			

settings = {
	"cookie_secret": _config.get("auth", "secret"),
	"login_url": "/auth",
	"xsrf_cookies": True,
	"static_path": "static",
}

application = tornado.web.Application([
	(r"/auth", GoogleHandler),
	(r"/", Containers),
	(r"/dashboard", Dashboard),
	(r"/create", CreateVM),
	(r"/billing", Billing),
	(r"/payreceive", PayReceive),
	(r"/spec", HostSpec),
	(r"/varnishRestart", VarnishRestart),
	(r"/vm/([0-9]+)", VMinfo),
	(r"/vm/([0-9]+)/edit", VMedit),
	(r"/vm/([0-9]+)/destroy", DestroyVM),
	(r"/vm/([0-9]+)/restart", RestartVM),
	(r"/vm/([0-9]+)/stop", StopVM),
	(r"/vm/([0-9]+)/start", StartVM),
	(r"/vm/([0-9]+)/claim", ClaimVM),
	(r"/vm/([0-9]+)/addweb", AddVarnish),
	(r"/vm/([0-9]+)/addport", AddPort),
	(r"/vm/([0-9]+)/munin", Munin),
	(r"/vm/([0-9]+)/root", RootPW),
	(r"/_cron", CronRun),
], **settings)

if __name__ == "__main__":
	http_server = tornado.httpserver.HTTPServer(application)
	http_server.listen(21212)
	import tornado.autoreload
	tornado.autoreload.start()
	tornado.ioloop.IOLoop.instance().start()
