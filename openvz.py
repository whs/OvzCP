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
	@property
	def ip(self):
		d = commands.getoutput("vzlist -a -H -o ip %s"%self.veid)
		return d.strip()
	@property
	def hostname(self):
		d = commands.getoutput("vzlist -a -H -o hostname %s"%self.veid)
		return d.strip()
	@property
	def os(self):
		return self.conf['OSTEMPLATE']
	@property
	def memlimit(self):
		""" soft cap of [guaranteed, burstable, max] (vmguar, privvm, oomguar) """
		return [self.conf['VMGUARPAGES'][0]*ARCH_PAGE, self.conf['PRIVVMPAGES'][0]*ARCH_PAGE, self.conf['OOMGUARPAGES'][0]*ARCH_PAGE]
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
	@property
	@online_only
	# TODO: When offline, still show total
	def diskinfo(self):
		""" [total, used, free] """
		d = commands.getoutput("vzctl exec %s df"%self.veid)
		d = re.split(" [ ]+", d.split("\n")[1])
		return [int(d[1])*1000, int(d[2])*1000, int(d[3])*1000]
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
	@property
	def conf(self):
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
		return subprocess.Popen("vzctl destroy "+str(self.veid), shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

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