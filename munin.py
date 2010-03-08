import os, sys, ConfigParser
sys.path.insert(0, os.path.join(os.getcwd(), "Jinja2-2.3-py2.5.egg"))
import jinja2

_config = ConfigParser.SafeConfigParser()
_config.read("config.ini")

def update(data, user):
	jinja = jinja2.Environment(loader=jinja2.loaders.FileSystemLoader("template"))
	d = jinja.get_template("munin.conf").render(munin=data, user=user)
	open("sysconf/munin.conf", "w").write(d)

def check_ip(ip, port=4949):
	import socket
	socket.setdefaulttimeout(0.2)
	try:
		s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		s.connect((ip, port))
	except socket.error:
		return False
	try:
		s.recv(4096)
	except socket.timeout:
		return False
	return True

if __name__ == "__main__":
	from models import Munin, User
	update(Munin.select(), User.select())