#!/usr/bin/python
# -*- encoding: utf-8
from __future__ import division

# trying to chdir() to dirname($0)
import os
if os.getuid() != 0:
	raise Exception, "OvzCP must be run as root"
try:
	os.chdir(os.path.dirname(__file__))
except OSError:
	pass

import sys
sys.path.insert(0, os.path.join(os.getcwd(), "tornado-2.1git-py2.5-linux-i686.egg"))
# Debian lenny's Jinja2 is older than 2.2 thus cannot be used
sys.path.insert(0, os.path.join(os.getcwd(), "Jinja2-2.3-py2.5.egg"))
sys.path.append(os.path.join(os.getcwd(), "netifaces-0.5-py2.5-linux-i686.egg"))

import models
import ConfigParser, cPickle, openvz, math, time, re, jinja2, netifaces, babel, gettext, hashlib, hmac
import varnish, simplejson
import tornado.httpserver, tornado.ioloop, tornado.web, tornado.auth, tornado.httpclient, tornado.options, urlparse

# parse config
_config = ConfigParser.SafeConfigParser()
_config.read("config.ini")

# Tornado 2.2 does not works on lenny by default
tornado.httpclient.AsyncHTTPClient.configure("tornado.curl_httpclient.CurlAsyncHTTPClient")

def xsrf_check(func):
	def f(self, *args, **kwargs):
		self.check_xsrf_cookie()
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
	burst = models.VM.select(models.VM.q.veid == vm.veid)[0].burst
	prices['burst'] = 0
	if burst:
		prices['burst'] = int(math.ceil(prices['total'] * (burst+1) * 0.5))
		prices['total'] = prices['total'] + prices['burst']
	if user:
		prices['time'] = (user.credit / prices['total'])*60
	if desc:
		return prices
	else:
		return prices['total']
def get_cloud_usage(user):
	if not _config.getboolean("cloudcp", "enabled"): return 0
	if "@" in user:
		user = re.findall("^(.*?)@", user)[0]
	import urllib
	d=urllib.urlopen(_config.get("cloudcp", "host")+"/cgi-bin/usage.exe?user="+user).read()
	d=tornado.escape.json_decode(d)
	return int(d['used'])

class BaseAuth(tornado.web.RequestHandler):
	def get_current_user(self):
		data = self.get_user()
		if data:
			return data
	def get_user(self):
		data = self.get_secure_cookie("auth")
		if data:
			userData = cPickle.loads(data)
			query = models.User.select(models.User.q.email == userData['email'])
			if query.count():
				return query[0]
			else:
				return models.User(email=userData['email'], credit=0)
	

class BaseHandler(BaseAuth):
	def get_user_locale(self):
		out = None
		if self.get_argument("_locale", None):
			out = self.get_argument("_locale")
			self.set_cookie("locale", out, expires_days=1000)
		if not out:
			out=self.get_cookie("locale", None)
		return out
	def prepare(self):
		self.gettext = gettext.translation('messages', os.path.join(os.getcwd(), "po"), [self.locale], fallback=True)
		self.gettext.install(True)
		# perform user agent detection
		agent = self.request.headers['User-Agent']
		# "Windows CE" is not in this list because it probably won't run the complex JavaScript
		# http://en.wikipedia.org/wiki/List_of_user_agents_for_mobile_phones
		# Note that the library we use supports for Apple devices, but I do not have access to one
		# so OvzCP is tested only against Android (N1 CyanogenMod) and webOS 1.4 emulator
		#
		# Also, we need to perform authentication which Google sucks and it just provide mobile web for Android
		#
		# TODO: Find Symbian^1's UA. Maybe asking @sahathai74?
		self._mobileWeb = False
		for x in ["iPhone", "iPod", "iPad", "BlackBerry", "Android", "webOS", "MSIEMobile 6.0", "Opera Mobi", "Opera Mini"]:
			if x in agent:
				self._mobileWeb = True
		if self.get_argument("_mobile", "auto") == "true":
			self._mobileWeb = True
		elif self.get_argument("_mobile", "auto") == "false":
			self._mobileWeb = False
	@property
	def locale(self):
		if not hasattr(self, "_locale"):
			self._locale = self.get_user_locale()
			if not self._locale:
				self._locale = self.get_browser_locale().code
				assert self._locale
		return self._locale
	def static_url(self, path):
		""" Copied from Tornadoweb source, added static.domain support """
		if not hasattr(self, "_static_hashes"):
			self._static_hashes = {}
		hashes = self._static_hashes
		if path not in hashes:
			import hashlib
			try:
				f = open(os.path.join(
					self.application.settings["static_path"], path))
				hashes[path] = hashlib.md5(f.read()).hexdigest()
				f.close()
			except:
				print "Could not open static file %r"%path
				hashes[path] = None
		base = "http://static."+_config.get("varnish", "ovzcphost") + "/"
		if hashes.get(path):
			return base + path + "?v=" + hashes[path][:5]
		else:
			return base + path
	def render(self, tmpl, *args, **kwargs):
		#totalcost = 0
		#for i in myVM(self.current_user, True):
		#	if i.vz.running:
		#		totalcost += vmBilling(i.vz)
		
		tmplPath = ["template"]
		if self._mobileWeb:
			tmplPath.insert(0, "template/mobile")
		jinja = jinja2.Environment(loader=jinja2.loaders.FileSystemLoader(tmplPath), extensions=['jinja2.ext.i18n'])
		jinja.install_gettext_translations(self.gettext)
		localeList = {"en": babel.Locale(self.locale).languages["en"]}
		for i in os.listdir("po"):
			if os.path.isdir(os.path.join("po", i)):
				localeList[i] = babel.Locale(self.locale).languages[i]
		margs = dict({
			# Python
			"str": str,
			# Internal Tornadoweb things
			"current_user": self.current_user,
			"static_url": self.static_url,
			"xsrf_form_html": self.xsrf_form_html,
			"xsrf": self.xsrf_token,
			"reverse_url": self.reverse_url,
			"locale": self.locale,
			"localeName": babel.Locale(self.locale).languages[self.locale],
			"localeList": localeList,
			"request": self.request,
			# OvzCP stuff
			"config": _config,
			#"totalcost": totalcost, 
			"cur_url":  self.request.full_url(),
			"auth_url": urlparse.urljoin(self.request.full_url(), "/auth")
		}, **kwargs)
		self.write(jinja.get_template(tmpl).render(*args, **margs))
		return
	def loading(self, act, vm=None, to="/"):
		# act in (start, stop, destroy)
		if not vm:
			veid = 0
		elif type(vm) == int:
			veid = vm
		else:
			veid = vm.veid
		if act == "start":
			txt = _("Starting %s") % veid
		elif act == "stop":
			txt = _("Stopping %s") % veid
		elif act == "destroy":
			txt = _("Destroying %s") % veid
		elif act == "create":
			txt = _("Creating VM")
		else:
			raise Exception, "Invalid act "+act
		
		tmplPath = ["template"]
		if self._mobileWeb:
			tmplPath.insert(0, "template/mobile")
		jinja = jinja2.Environment(loader=jinja2.loaders.FileSystemLoader(tmplPath), extensions=['jinja2.ext.i18n'])
		jinja.install_gettext_translations(self.gettext)
		localeList = {"en": babel.Locale(self.locale).languages["en"]}
		for i in os.listdir("po"):
			if os.path.isdir(os.path.join("po", i)):
				localeList[i] = babel.Locale(self.locale).languages[i]
		self.write(jinja.get_template("poller.html").render(static_url=self.static_url, reverse_url=self.reverse_url, veid=veid, codeact=act, act=txt, to=to))

class APIHandler(BaseAuth):
	static_url = BaseHandler.static_url
	current_user = None
	def get_current_user(self):
		data = self.get_user()
		if data:
			return data
		# check the apikey
		try:
			key = self.get_argument("apikey")
		except Exception, e:
			self.error(`e`)
			return
		try:
			key = models.APIKey.selectBy(id=key)[0]
		except IndexError, e:
			self.error("No such API key")
			return
		# then make sure the nonce is not used
		try:
			nonce = self.get_argument("nonce")
		except Exception, e:
			self.error(`e`)
			return
		if len(nonce) > 50:
			self.error("Nonce is too long")
			return
		sqlnonce = models.APINonce.select(models.APINonce.q.nonce==nonce)
		if sqlnonce.count() > 0:
			if sqlnonce[0].key == key:
				self.error("Nonce used")
				return
		# check the  URL!
		query = self.request.query
		try:
			query = re.sub("(?:&|)hash="+self.get_argument("hash"), "", query)
		except Exception, e:
			self.error(`e`)
			return
		if hmac.new(key.key, query, hashlib.sha1).hexdigest() != self.get_argument("hash"):
			self.error("Invalid signature. The request part you need to be signed is "+query)
			return
		# Add nonce to the database
		models.APINonce(nonce=nonce, key=key)
		return key.user
	def error(self, error):
		return self.json({"error": error})
	def json(self, dat):
		self.set_header("Content-Type", "text/json; charset=UTF-8")
		self.write(dat)

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

class Poller(BaseHandler):
	@tornado.web.authenticated
	def get(self):
		self.loading(self.get_argument("act"), int(self.get_argument("veid")), self.get_argument("next"))

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
		d = commands.getoutput("df -P")
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
			self.redirect(self.reverse_url("containers")+"?error=6")
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
			elif e == "5":
				err = _("Verification failed. Did you double-submitted the form?")
		import random
		nonce=models.Nonce().id
		self.render("create.html", templates=openvz.listTemplates(), hostnames = hostnames,
			title=_("Creating VM"), error=err, nonce=nonce)
	@tornado.web.asynchronous
	@tornado.web.authenticated
	def post(self):
		if self.current_user.credit < 5000:
			self.redirect(self.reverse_url("containers")+"?error=6")
			return
		if not self.get_argument("tos", False):
			self.redirect(self.reverse_url("createvm")+"?error=1")
			return
		if self.get_argument("os", "_/|\_") not in openvz.listTemplates():
			self.redirect(self.reverse_url("createvm")+"?error=2")
			return
		if self.get_argument("root", "omgwtflol") != self.get_argument("root2", "roflcopters"):
			self.redirect(self.reverse_url("createvm")+"?error=3")
			return
		hostnames = map(lambda x: x.hostname,openvz.listVM())
		if not re.match("^([\.0-9A-Za-z_\-]+)$", self.get_argument("hostname", "^^!!!!")) or self.get_argument("hostname") in hostnames:
			self.redirect(self.reverse_url("createvm")+"?error=4")
			return
		try:
			models.Nonce.get(int(self.get_argument("nonce"))).destroySelf()
		except:
			self.redirect(self.reverse_url("createvm")+"?error=5")
			return
		try:
			veid = openvz.listVM()[-1].veid+1
		except IndexError:
			veid = 101
		if not models.VM.select(models.VM.q.veid == veid).count():
			models.VM(veid=veid, user=self.current_user)
		else:
			v = models.VM.select(models.VM.q.veid == veid)[0]
			v.user = self.current_user
		self.redirect(self.reverse_url("containers"))
		vm=openvz.createVM(self.get_argument("os"), veid, _config.get("iface", "nameserver"), self.get_argument("root"))
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

class DestroyVM(BaseHandler):
	@tornado.web.authenticated
	@xsrf_check
	def get(self, veid):
		vm = openvz.VM(int(veid))
		self.render("destroy.html", veid=veid, hostname=vm.hostname, credit=vmBilling(vm), title=_("Destroy %s")%veid)
	@tornado.web.authenticated
	def post(self, veid):
		sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		if sql.user != self.current_user and sql.user:
			self.redirect(self.reverse_url("containers")+"?error=1")
			return
		vm = sql.vz
		if vm.running:
			self.redirect(self.reverse_url("containers")+"?error=5")
			return
		proc = vm.destroy()
		for i in sql.varnishBackend:
			for i2 in i.cond:
				i2.destroySelf()
			i.destroySelf()
		for i in sql.portForward:
			i.destroySelf()
		if sql.munin:
			sql.munin.destroySelf()
		import munin, vmfw
		munin.update(models.Munin.select(), models.User.select())
		vmfw.update(models.PortForward.select())
		vmfw.restart()
		varnish.updateBackend(models.VarnishBackend.select())
		varnish.updateRecv(models.VarnishCond.select())
		varnish.restart()
		sql.destroySelf()
		time.sleep(1) # wait for dusts to settle
		self.redirect(self.get_argument("return", self.reverse_url("containers")+"?msg=3"))

class RestartVM(BaseHandler):
	@tornado.web.authenticated
	@tornado.web.asynchronous
	@xsrf_check
	def get(self, veid):
		sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		if sql.user != self.current_user and sql.user:
			self.redirect(self.reverse_url("containers")+"?error=1")
			return
		vm = sql.vz
		if not vm.running:
			self.redirect(self.reverse_url("containers")+"?error=2")
			return
		self.redirect(self.get_argument("return", self.reverse_url("vminfo", veid)))
		vm.restart()

class StopVM(BaseHandler):
	@tornado.web.authenticated
	@tornado.web.asynchronous
	@xsrf_check
	def get(self, veid):
		sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		if sql.user != self.current_user and sql.user:
			self.redirect(self.reverse_url("containers")+"?error=1")
			return
		vm = sql.vz
		if not vm.running:
			self.redirect(self.reverse_url("containers")+"?error=2")
			return
		self.redirect(self.get_argument("return", self.reverse_url("vminfo", veid)))
		vm.stop()

class StartVM(BaseHandler):
	@tornado.web.authenticated
	@tornado.web.asynchronous
	@xsrf_check
	def get(self, veid):
		if self.current_user.credit < 1000:
			self.redirect(self.reverse_url("containers")+"?error=4")
			return
		sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		if sql.user != self.current_user and sql.user:
			self.redirect(self.reverse_url("containers")+"?error=1")
			return
		vm = sql.vz
		if vm.running:
			self.redirect(self.reverse_url("containers")+"?error=2")
			return
		self.redirect(self.get_argument("return", self.reverse_url("vminfo", veid)))
		vm.start()

class ClaimVM(BaseHandler):
	@tornado.web.authenticated
	def get(self, veid):
		sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		if not self.get_argument("revert", False):
			if sql.user:
				self.redirect(self.reverse_url("containers")+"?error=1")
				return
			if sql.user == self.current_user:
				self.redirect(self.reverse_url("containers")+"?error=3")
				return
			sql.set(user=self.current_user)
		else:
			return
			if not sql.user:
				self.redirect(self.reverse_url("containers")+"?error=1")
				return
			if sql.user != self.current_user:
				self.redirect(self.reverse_url("containers")+"?error=1")
				return
			sql.set(user=None)
		self.redirect(self.get_argument("return", self.reverse_url("vminfo", veid)))

class VMinfo(BaseHandler):
	@tornado.web.authenticated
	def get(self, veid):
		try:
			sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		except IndexError:
			self.redirect(self.reverse_url("containers")+"?error=1")
			return
		if sql.user != self.current_user and sql.user:
			self.redirect(self.reverse_url("containers")+"?error=1")
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
			elif err == "6":
				errmsg = _("Reverse HTTP proxy is enabled. Please use web forwarding instead")
			elif err == "7":
				errmsg = _("Invalid burst level")
		if self.get_argument("message", None):
			msg = self.get_argument("message")
			if msg == "1":
				txtmsg = _("Settings commited.")
			elif msg == "2":
				txtmsg = _("No changes.")
			elif msg == "3":
				txtmsg = _("Root password successfully changed")
			elif msg == "4":
				txtmsg = _("Burst level set")
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
			varnishRestart=varnish.version()[0] < 2, error=errmsg, message=txtmsg, interface=interface)

class VMedit(BaseHandler):
	@tornado.web.authenticated
	def get(self, veid):
		try:
			sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		except IndexError:
			self.redirect(self.reverse_url("containers")+"?error=1")
			return
		if sql.user != self.current_user and sql.user:
			self.redirect(self.reverse_url("containers")+"?error=1")
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
			self.redirect(self.reverse_url("containers")+"?error=1")
			return
		if sql.user != self.current_user and sql.user:
			self.redirect(self.reverse_url("containers")+"?error=1")
			return
		hostnames = map(lambda x: x.hostname,openvz.listVM())
		if self.get_argument("hostname") in hostnames and self.get_argument("hostname") != sql.vz.hostname:
			self.redirect(self.reverse_url("vminfo", veid)+"?error=3")
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
			if sql.vz.running:
				sql.vz.restart().wait()
			self.redirect(self.reverse_url("vminfo", veid)+"?message=1")
		else:
			self.redirect(self.reverse_url("vminfo", veid)+"?message=2")

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
		cloud = get_cloud_usage(self.current_user.email)
		totalcost = 0
		for i in myVM(self.current_user, True):
			if i.vz.running:
				totalcost += vmBilling(i.vz)
		self.render("billing.html", vmcost=vmcost, title=_("Billing"), cloud=cloud, totalcost=totalcost)

class RootPW(BaseHandler):
	@tornado.web.authenticated
	def post(self, veid):
		sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		if sql.user != self.current_user or not sql.user:
			self.redirect(self.reverse_url("containers")+"?error=1")
			return
		if self.get_argument("root", "omgwtflol") != self.get_argument("root2", "roflcopters"):
			self.redirect(self.reverse_url("vminfo", veid)+"?error=5")
			return
		sql.vz.root_password(self.get_argument("root"))
		self.redirect(self.reverse_url("vminfo", veid)+"?message=3")

class Burst(BaseHandler):
	@tornado.web.authenticated
	def post(self, veid):
		sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		if sql.user != self.current_user or not sql.user:
			self.redirect(self.reverse_url("containers")+"?error=1")
			return
		burst = int(self.get_argument("burst"))-1
		if burst < 0 or burst > 9:
			self.redirect(self.reverse_url("vminfo", veid)+"?error=7")
		sql.burst = burst
		sql.vz.conf = {"cpuunits": (burst*1000) + 1000}
		self.redirect(self.reverse_url("vminfo", veid)+"?message=4")

class Credit(BaseHandler):
	def get(self):
		self.write(open("template/credit.html").read().replace("{{static_url('jquery.js')}}", self.static_url("jquery.js")))

class AddPort(BaseHandler):
	@tornado.web.authenticated
	@xsrf_check
	def get(self, veid):
		if not _config.getboolean("iface", "enabled"): return
		try:
			d=models.PortForward.select(models.PortForward.q.id == int(self.get_argument("delete")))[0]
		except IndexError:
			self.redirect(self.reverse_url("vminfo", veid)+"#portedit")
		if d.vm.user != self.current_user or not d.vm.user:
			self.redirect(self.reverse_url("containers")+"?error=1")
			return
		d.destroySelf()
		import vmfw
		vmfw.update(models.PortForward.select())
		vmfw.restart()
		self.redirect(self.reverse_url("vminfo", veid)+"#portedit")
	@tornado.web.authenticated
	def post(self, veid):
		if not _config.getboolean("iface", "enabled"): return
		sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		if sql.user != self.current_user or not sql.user:
			self.redirect(self.reverse_url("containers")+"?error=1")
			return
		if not re.match(_config.get("iface", "allowed"), self.get_argument("iface")):
			self.redirect(self.reverse_url("vminfo", veid)+"?error=4")
			return
		try:
			if _config.get("ifaceuser", self.get_argument("iface").replace(":", "-")) != self.current_user.email:
				self.redirect(self.reverse_url("vminfo", veid)+"?error=4")
				return
		except ConfigParser.NoOptionError:
			pass
		inport = self.get_argument("port", None)
		outport = self.get_argument("outport", None)
		if inport and not outport:
			outport = inport
		elif outport and not inport:
			inport = outport
		elif not inport and not outport:
			self.redirect(self.reverse_url("vminfo", veid)+"?error=4")
			return
		if outport.lower() == "dmz":
			outport = -1
			inport = -1
			if models.PortForward.select(models.PortForward.q.iface==self.get_argument("iface")).count():
				self.redirect(self.reverse_url("vminfo", veid)+"?error=1")
				return
		else:
			outport = int(outport) 
			inport = int(inport)
		if outport == 80 and _config.get("varnish", "enabled"):
			self.redirect(self.reverse_url("vminfo", veid)+"?error=6")
			return
		if models.PortForward.select(models.AND(models.PortForward.q.iface==self.get_argument("iface"), 
				models.OR(models.PortForward.q.outport==outport, models.PortForward.q.outport==-1))).count():
			self.redirect(self.reverse_url("vminfo", veid)+"?error=1")
			return
		models.PortForward(vm=sql, iface=self.get_argument("iface"), port=inport, outport=outport)
		import vmfw
		vmfw.update(models.PortForward.select())
		vmfw.restart()
		self.redirect(self.reverse_url("vminfo", veid)+"#portedit")

class AddVarnish(BaseHandler):
	@tornado.web.authenticated
	@xsrf_check
	def get(self, veid):
		if not _config.getboolean("varnish", "enabled"): return
		try:
			d=models.VarnishCond.select(models.VarnishCond.q.id == int(self.get_argument("delete")))[0]
		except IndexError:
			self.redirect(self.reverse_url("vminfo", veid)+"#webedit")
		if d.backend.vm.user != self.current_user or not d.backend.vm.user:
			self.redirect(self.reverse_url("containers")+"?error=1")
			return
		# check for orphaned backend
		backend = d.backend
		d.destroySelf()
		varnish.updateRecv(models.VarnishCond.select())
		if backend.cond.count() == 0:
			backend.destroySelf()
			varnish.updateBackend(models.VarnishBackend.select())
		self.redirect(self.reverse_url("vminfo", veid)+"#webedit")
	@tornado.web.authenticated
	def post(self, veid):
		if not _config.getboolean("varnish", "enabled"): return
		sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		if sql.user != self.current_user or not sql.user:
			self.redirect(self.reverse_url("containers")+"?error=1")
			return
		host = self.get_argument("host", "")
		port = int(self.get_argument("port", 0))
		if not host or not port:
			self.redirect(self.reverse_url("vminfo", veid)+"#webedit")
			return
		if not re.match(r"^[a-zA-Z0-9\.\-_]+$", host):
			self.redirect(self.reverse_url("vminfo", veid)+"?error=3")
			return
		if models.VarnishCond.select(models.VarnishCond.q.hostname==host).count():
			self.redirect(self.reverse_url("vminfo", veid)+"?error=1")
			return
		backend = models.VarnishBackend.select(models.AND(models.VarnishBackend.q.port == port, models.VarnishBackend.q.vm==sql))
		backendUpdate=False
		if backend.count():
			backend = backend[0]
		else:
			backend = models.VarnishBackend(name=sql.vz.hostname+str(port), vm=sql, port=port)
			backendUpdate=True
		models.VarnishCond(hostname=host, subdomain=bool(self.get_argument("subdomain", False)), varnishBackend=backend)
		if backendUpdate:
			varnish.updateBackend(models.VarnishBackend.select())
		varnish.updateRecv(models.VarnishCond.select())
		if varnish.version()[0] > 1:
			varnish.restart()
		self.redirect(self.reverse_url("vminfo", veid)+"#webedit")

class Munin(BaseHandler):
	@tornado.web.authenticated
	def post(self, veid):
		self.set_header("Content-type", "text/json")
		if not _config.getboolean("munin", "enabled"): return
		sql = models.VM.select(models.VM.q.veid == int(veid))[0]
		if sql.user != self.current_user or not sql.user:
			self.write(simplejson.dumps({"error": _("VM not owned by current user")}))
			return
		if self.get_argument("status") == "toggle":
			e = not sql.munin
		else:
			e = self.get_argument("status") == "true"
		import munin
		if e:
			if not munin.check_ip(sql.vz.ip):
				self.write(simplejson.dumps({"error": _("Cannot connect to Munin on the VM.")}))
				return
			models.Munin(vm=sql)
		else:
			sql.munin.destroySelf()
		munin.update(models.Munin.select(), models.User.select())
		self.write(simplejson.dumps({"status": bool(sql.munin)}))

class VarnishRestart(BaseHandler):
	@tornado.web.authenticated
	@xsrf_check
	def get(self):
		if not _config.getboolean("varnish", "enabled"): return
		if varnish.version()[0] < 2:
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
				varnish.restart()
		else:
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
	@tornado.web.authenticated
	def post(self):
		self.set_header("Content-type", "text/json")
		data = self.get_argument("data")
		if data == "vmload":
			out = {}
			for i in myVM(self.current_user, True):
				if i.vz.running:
					out[i.vz.hostname] = i.vz.loadAvg[0]
			d = open("/proc/loadavg").read()
			loadAvg= map(lambda x:float(x), d.split(" ")[:3])
			out[_('Host OS')] = loadAvg[0]
			self.write(simplejson.dumps([out]))

class Cloud(BaseHandler):
	@tornado.web.authenticated
	@tornado.web.asynchronous
	def get(self):
		if not _config.getboolean("cloudcp", "enabled"): return
		u = re.findall("^(.*?)@", self.current_user.email)[0]
		http = tornado.httpclient.AsyncHTTPClient()
		http.fetch(_config.get("cloudcp", "host")+"/cgi-bin/usage.exe?user="+u, callback=self.async_callback(self.on_response))
	def on_response(self, res):
		d=tornado.escape.json_decode(res.body)
		u = re.findall("^(.*?)@", self.current_user.email)[0]
		self.render("cloud.html", title=_("Cloud Storage"), usage=int(d['used']), user=u)
		self.finish()
	@tornado.web.authenticated
	def post(self):
		if not _config.getboolean("cloudcp", "enabled"): return
		self.set_header("Content-type", "text/json")
		if self.current_user.credit <= 0: return
		acc=open("cloudcp/users").readlines()
		u = re.findall("^(.*?)@", self.current_user.email)[0]
		acd={}
		for i in acc:
			i = i.strip().split("\t")
			acd[i[0]] = i[1]
		import hashlib, string, random
		def genpw(length=8, chars=string.letters + string.digits):
			return ''.join([random.choice(chars) for i in range(length)])
		pw = genpw()
		acd[u] = hashlib.md5(u+":CloudCP:"+pw).hexdigest()
		fp=open("cloudcp/users", "w")
		for i in acd.iteritems():
			fp.write("\t".join(i)+"\n")
		self.write(simplejson.dumps({"user": u, "password": pw}))

class APIWeb(BaseHandler):
	@tornado.web.authenticated
	def get(self):
		if self.get_argument("delete", None):
			delk = self.get_argument("delete")
			delk = models.APIKey.selectBy(id=delk)[0]
			if delk.user == self.current_user:
				delk.destroySelf()
			else:
				self.write("Hack?")
				return
			self.redirect(self.reverse_url("apiweb"))
			return
		self.render("api.html", title="API", apikey=models.APIKey.selectBy(user=self.current_user))
	@tornado.web.authenticated
	def post(self):
		import hashlib, string, random
		def genpw(length=8, chars=string.letters + string.digits):
			return ''.join([random.choice(chars) for i in range(length)])
		key = genpw(24)
		models.APIKey(user=self.current_user, key=key)
		return self.get()

class APIInfo(APIHandler):
	def get(self):
		self.current_user = self.get_current_user()
		if not self.current_user:
			return
		veid = self.get_argument("veid", None)
		if not veid:
			self.error("Please specify veid.")
			return
		try:
			veid = int(veid)
		except ValueError:
			self.error("VEID is not int")
			return
		vm = models.VM.selectBy(veid=veid)
		if vm.count() == 0:
			self.error("No such VM")
			return
		vm = vm[0]
		if vm.user != self.current_user:
			self.error("VM not owned by current user")
			return
		data = {}
		data['running'] = vm.vz.running
		data['ip'] = vm.vz.ip
		data['hostname'] = vm.vz.hostname
		data['os'] = vm.vz.os
		data['memlimit'] = vm.vz.memlimit
		data['diskinfo'] = vm.vz.diskinfo
		data['uptime'] = vm.vz.uptime
		data['loadAvg'] = vm.vz.loadAvg
		
		if data['running']:
			data['nproc'] = vm.vz.nproc
			data['meminfo'] = vm.vz.meminfo
		
		self.json(data)

class  APIAction(APIHandler):
	def get(self):
		self.current_user = self.get_current_user()
		if not self.current_user:
			return
		veid = self.get_argument("veid", None)
		if not veid:
			self.error("Please specify veid.")
			return
		try:
			veid = int(veid)
		except ValueError:
			self.error("VEID is not int")
			return
		vm = models.VM.selectBy(veid=veid)
		if vm.count() == 0:
			self.error("No such VM")
			return
		vm = vm[0]
		if vm.user != self.current_user:
			self.error("VM not owned by current user")
			return
		action = self.get_argument("action", None)
		if not action:
			self.error("Please specify action")
			return
		if action == "start":
			vm.vz.start()
			self.json({"result": True})
		elif action == "stop":
			vm.vz.stop()
			self.json({"result": True})
		elif action == "restart":
			vm.vz.restart()
			self.json({"result": True})
		else:
			self.error("Invalid action. Note that destroy is not supported for security reason.")
		

class GoogleHandler(BaseHandler, tornado.auth.GoogleMixin):
	@tornado.web.asynchronous
	def get(self):
		# clear old cookie!!
		self.set_secure_cookie("auth", "")
		self.next = self.get_argument("next", "/")
		if self.next.startswith(self.reverse_url("auth")):
			self.next = self.reverse_url("dashboard")
		if self.get_argument("openid.mode", None):
			self.get_authenticated_user(self.async_callback(self._on_auth))
			return
		self.authorize_redirect("https://www.google.com/m8/feeds/")
	def _on_auth(self, user):
		if not user:
			raise tornado.web.HTTPError(500, "Google auth failed")
		self.set_secure_cookie("auth", cPickle.dumps(user))
		self.redirect(self.next)

class CronRun(BaseHandler):
	def get(self):
		import urllib
		self.set_header("Content-type", "text/plain")
		if self.get_argument("cron_key") != _config.get("auth", "cron_key"):
			self.write("Invalid cron key")
			print "CRON: Invalid cron key\n"
			return
		proclist = []
		acd={} # cloud storage account db
		for i in open("cloudcp/users").readlines():
			i = i.strip().split("\t")
			acd[i[0]] = i[1]
		acdChange = False
		for u in models.User.select():
			totalcost = 0
			for i in myVM(u, True):
				if i.vz.running:
					totalcost += vmBilling(i.vz)
			u.credit -= totalcost
			if _config.getboolean("cloudcp", "enabled"):
				sun = re.findall("^(.*?)@", u.email)[0]
				cloudusage = get_cloud_usage(sun)
				u.credit -= math.ceil((_config.getint("cloudcp", "price")/_config.getint("cloudcp", "pricePer"))*(cloudusage/1000))
			if u.credit <= 0:
				# debug message are disabled because it would repeat several times
				#print "CRON: User "+u.email+" run out of credit"
				self.write(u.email+" out of credit\n")
				for i in myVM(u, True):
					if i.vz.running:
						proclist.append(i.vz.stop())
				if _config.getboolean("cloudcp", "enabled"):
					#print "CRON: Removed CloudCP login"
					try:
						del acd[sun]
					except KeyError:
						pass
					acdChange = True
		if acdChange:
			fp=open("cloudcp/users", "w")
			for i in acd.iteritems():
				fp.write("\t".join(i)+"\n")
		for i in proclist:
			i.wait()
		self.write("\n\nCron ran\n")

class Stylesheet(BaseHandler):
	def process_css(self, f, sub=False):
		d=open(f).read()
		incl = re.findall("(@import url\((.*?)\);)", d)
		if incl:
			for i in incl:
				d = d.replace(i[0], self.process_css(os.path.join(os.path.dirname(f), i[1]), True))
		static = re.findall("(url\((.*?)\))", d)
		if static and not sub:
			for i in static:
				d = d.replace(i[0], "url("+self.static_url(i[1].replace(" ", "%20"))+")")
		d = d.replace("\n", "").replace("\t", "")
		d = re.sub("/\*(.*?)\*/", "", d)
		return d
	def get(self):
		import stat, datetime, email
		self.set_header("Content-Type", "text/css")
		stat_result = os.stat("static/style.css")
		modified = datetime.datetime.fromtimestamp(stat_result[stat.ST_MTIME])
		self.set_header("Last-Modified", modified)
		self.set_header("Expires", datetime.datetime.utcnow() + \
									datetime.timedelta(days=365))
		self.set_header("Cache-Control", "public, max-age=" + str(86400*365))
		ims_value = self.request.headers.get("If-Modified-Since")
		if ims_value is not None:
			date_tuple = email.utils.parsedate(ims_value)
			if_since = datetime.datetime.fromtimestamp(time.mktime(date_tuple))
			if if_since >= modified:
				self.set_status(304)
				return
		data = self.process_css("static/style.css")
		self.set_header("Content-Length", len(data))
		self.write(data)
			

settings = {
	"cookie_secret": _config.get("auth", "secret"),
	"login_url": "/auth",
	"xsrf_cookies": True,
	"static_path": "static",
	"gzip": True,
	"debug": False
}

application = tornado.web.Application([
	tornado.web.URLSpec(r"/auth", GoogleHandler, name="auth"),
	tornado.web.URLSpec(r"/", Dashboard, name="dashboard"),
	tornado.web.URLSpec(r"/poller", Poller, name="poller"),
	tornado.web.URLSpec(r"/containers", Containers, name="containers"),
	tornado.web.URLSpec(r"/create", CreateVM, name="createvm"),
	tornado.web.URLSpec(r"/billing", Billing, name="billing"),
	tornado.web.URLSpec(r"/spec", HostSpec, name="hostspec"),
	tornado.web.URLSpec(r"/varnishRestart", VarnishRestart, name="varnishrestart"),
	tornado.web.URLSpec(r"/cloud", Cloud, name="cloud"),
	tornado.web.URLSpec(r"/vm/([0-9]+)", VMinfo, name="vminfo"),
	tornado.web.URLSpec(r"/vm/([0-9]+)/edit", VMedit, name="vmedit"),
	tornado.web.URLSpec(r"/credit", Credit, name="credit"),
	tornado.web.URLSpec(r"/vm/([0-9]+)/destroy", DestroyVM, name="destroyvm"),
	tornado.web.URLSpec(r"/vm/([0-9]+)/restart", RestartVM, name="restartvm"),
	tornado.web.URLSpec(r"/vm/([0-9]+)/stop", StopVM, name="stopvm"),
	tornado.web.URLSpec(r"/vm/([0-9]+)/start", StartVM, name="startvm"),
	tornado.web.URLSpec(r"/vm/([0-9]+)/claim", ClaimVM, name="claimvm"),
	tornado.web.URLSpec(r"/vm/([0-9]+)/addweb", AddVarnish, name="addvarnish"),
	tornado.web.URLSpec(r"/vm/([0-9]+)/addport", AddPort, name="addport"),
	tornado.web.URLSpec(r"/vm/([0-9]+)/munin", Munin, name="munin"),
	tornado.web.URLSpec(r"/vm/([0-9]+)/root", RootPW, name="rootpw"),
	tornado.web.URLSpec(r"/vm/([0-9]+)/burst", Burst, name="burst"),
	tornado.web.URLSpec(r"/_cron", CronRun, name="cron"),
	
	# API
	tornado.web.URLSpec(r"/api", APIWeb, name="apiweb"),
	tornado.web.URLSpec(r"/api/info", APIInfo, name="api_info"),
	tornado.web.URLSpec(r"/api/action", APIAction, name="api_action"),
	
	tornado.web.URLSpec(r"/style.css", Stylesheet, name="css")
], **settings)

if __name__ == "__main__":
	tornado.options.define('port', type=int, default=21215)
	tornado.options.parse_command_line()
	debug = False
	if debug:
		import tornado.autoreload
		tornado.autoreload.start()
	http_server = tornado.httpserver.HTTPServer(application)
	http_server.listen(tornado.options.options.port)
	tornado.ioloop.IOLoop.instance().start()
