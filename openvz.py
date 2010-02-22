import commands, re, subprocess
class VM(object):
	veid = 0
	def __init__(self, veid):
		self.veid = int(veid)
	def __repr__(self):
		return str(self.hostname)
	@property
	def nproc(self):
		d = commands.getoutput("vzlist -a -H -o numproc %s"%self.veid)
		return int(d.strip())
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
		conf = open("/etc/vz/conf/"+str(self.veid)+".conf").read()
		return re.findall('OSTEMPLATE=(.*?)', conf)[0]
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

def list():
	out = []
	for i in commands.getoutput("vzlist -a -H -o veid").split("\n"):
		out.append(VM(i.strip()))
	return out
