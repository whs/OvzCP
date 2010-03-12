import commands, re, subprocess, os
ARCH_PAGE = 4 * 1000  # memory pages of current arch, on i386/amd64 is 4kB, ia64 is 16kB
service_proc = {
	"apache": ["apache", "apache2", "httpd"],
	"mysql": ["mysqld"],
	"mail": ["exim4", "exim", "postfix"],
}
def online_only(func):
	def f(self, *args, **kwargs):
		if self.running:
			return func(self, *args, **kwargs)
		else:
			return False
	return f
class VM(object):
	veid = 0
	def __init__(self, veid):
		self.veid = int(veid)
	def __repr__(self):
		return str(self.hostname)
	@property
	def nproc(self):
		d = commands.getoutput("vzlist -a -H -o numproc %s"%self.veid)
		try:
			return int(d.strip())
		except ValueError:
			return None
	@property
	def running(self):
		d = commands.getoutput("vzlist -a -H -o status %s"%self.veid)
		return d.strip() == "running"
	
	def get_ip(self):
		d = commands.getoutput("vzlist -a -H -o ip %s"%self.veid)
		return d.strip()
	def set_ip(self, ip, remove_ip="all"):
		self.set_conf("ipdel", remove_ip)
		return self.set_conf("ipadd", ip)
	ip = property(get_ip, set_ip)
	
	def get_hostname(self):
		d = commands.getoutput("vzlist -a -H -o hostname %s"%self.veid)
		if d.strip() == "-": d=""
		return d.strip()
	def set_hostname(self, hostname):
		return self.set_conf("hostname", hostname)
	hostname = property(get_hostname, set_hostname)
	
	@property
	def os(self):
		return self.conf['OSTEMPLATE']
	
	def get_memlimit(self):
		""" soft cap of [guaranteed, burstable, max] (vmguar, privvm, oomguar) """
		return [self.conf['VMGUARPAGES'][0]*ARCH_PAGE, self.conf['PRIVVMPAGES'][0]*ARCH_PAGE, self.conf['OOMGUARPAGES'][0]*ARCH_PAGE]
	def set_memlimit(self, memlimit):
		""" units are in kilobyte """
		min, burst, max = memlimit
		try:
			old = self.get_memlimit()
		except:
			old = [-1,-1,-1]
		changed = False
		if old[0] != min:
			self.set_conf("vmguarpages", "%s:%s"%(int(min/ARCH_PAGE), int(min/ARCH_PAGE)))
			changed = True
		if old[1] != burst:
			self.set_conf("privvmpages", "%s:%s"%(int(burst/ARCH_PAGE), int(burst/ARCH_PAGE)))
			changed = True
		if old[2] != max:
			self.set_conf("oomguarpages", "%s:%s"%(int(max/ARCH_PAGE), int(max/ARCH_PAGE)))
			changed = True
		return changed
	memlimit = property(get_memlimit, set_memlimit)
	
	@property
	@online_only
	def meminfo(self):
		d = commands.getoutput("vzctl exec %s cat /proc/meminfo"%self.veid)
		out = {}
		for i in d.split("\n"):
			i = re.split(":[ ]+", i)
			if i[1].endswith(" kB"):
				i[1] = int(i[1].split(" ")[0])*1024
			out[i[0]] = i[1]
		return out
	
	def get_diskinfo(self):
		""" [total, used, free] """
		if self.running:
			cmd = "stat"
		else:
			cmd = "show"
		d = commands.getoutput("vzquota %s %s"%(cmd, self.veid))
		d = re.split("[ ]+", d.split("\n")[1].strip())
		usage = d[1]
		if usage.endswith("*"): usage = usage[:-1]
		try:
			usage = int(usage)
		except ValueError:
			return [1,1,0]
		total = int(d[2]) # soft limit
		return [total, usage, total-usage]
	def set_diskinfo(self, space):
		""" Space's unit is in kilobyte """
		return self.set_conf("diskspace", "%s:%s"%(int(space), int(space+(space*20//100))))
	diskinfo = property(get_diskinfo, set_diskinfo)
	
	@property
	def uptime(self):
		if not self.running:
			return 0
		else:
			return float(commands.getoutput("vzctl exec %s cat /proc/uptime"%self.veid).split(" ")[0])
	@property
	def loadAvg(self):
		if not self.running:
			return [0, 0, 0]
		else:
			d = commands.getoutput("vzctl exec %s cat /proc/loadavg"%self.veid)
			return map(lambda x:float(x), d.split(" ")[:3])
	
	def get_conf(self):
		conf = open("/etc/vz/conf/"+str(self.veid)+".conf").read()
		out = {}
		for i in re.findall('(.*?)=(?:"|)(.*?)(?:"|\n)', conf):
			i = list(i)
			# FIXME: any better function
			if ":" in i[1]:
				i[1] = i[1].split(":")
				i[1] = [int(i[1][0]), int(i[1][1])]
			try:
				i[1] = int(i[1])
			except ValueError:
				pass
			except TypeError:
				pass
			out[i[0]] = i[1]
		return out
	def set_conf(self, key, value=""):
		if value:
			if value == True:
				value = "yes"
			elif value == False:
				value = "no"
			return commands.getoutput("vzctl set %s --%s %s --save"%(self.veid, key.lower(), value))
		else:
			for i in key.iteritems():
				self.set_conf(*i)
	conf = property(get_conf, set_conf)
	
	def start(self):
		if self.running:
			return False
		return subprocess.Popen("vzctl start "+str(self.veid), shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	def restart(self):
		if not self.running:
			return False
		return subprocess.Popen("vzctl restart "+str(self.veid), shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	def stop(self):
		if not self.running:
			return False
		return subprocess.Popen("vzctl stop "+str(self.veid), shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	def destroy(self):
		if self.running:
			return False
		# any more security?
		subprocess.Popen("vzctl destroy "+str(self.veid), shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).wait()
		try:
			os.unlink("/etc/vz/"+str(self.veid)+".conf.destroyed")
		except OSError:
			pass
	def root_password(self, passwd, user="root"):
		return self.set_conf('userpasswd', user+':'+passwd)

def listVM():
	out = []
	for i in commands.getoutput("vzlist -a -H -o veid").split("\n"):
		out.append(VM(i.strip()))
	return out
def listTemplates():
	out = []
	for i in os.listdir("/var/lib/vz/template/cache/"):
		out.append(i.replace(".tar.gz", ""))
	return out
def createVM(template, veid=None, nameserver=None, root=None):
	if not veid:
		try:
			veid = listVM()[-1].veid+1
		except IndexError:
			veid = 101
	status = os.system("vzctl create %s --ostemplate %s --config vps.basic"%(veid, template))
	#if status != 0:
	#	raise Exception, "vzctl create exited with status "+str(status)
	vm=VM(veid)
	vm.conf = {"onboot": True, "nameserver": nameserver}
	if root:
		vm.root_password(root)
	return vm
