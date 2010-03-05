import os, sys
sys.path.insert(0, os.path.join(os.getcwd(), "Jinja2-2.3-py2.5.egg"))
sys.path.append(os.path.join(os.getcwd(), "netifaces-0.5-py2.5-linux-i686.egg"))
import jinja2, netifaces

# iptables forwarding configuration generator
def update(data):
	jinja = jinja2.Environment(loader=jinja2.loaders.FileSystemLoader("template"))
	ip={}
	for iface in netifaces.interfaces():
		try:
			ip[iface] = netifaces.ifaddresses(iface)[netifaces.AF_INET][0]['addr']
		except KeyError:
			pass
		except ValueError:
			pass
	d = jinja.get_template("vmfw.sh").render(port=data, ip=ip)
	open("sysconf/vmfw.sh", "w").write(d)

def restart():
	os.system("sysconf/vmfw.sh")

if __name__ == "__main__":
	from models import PortForward
	update(PortForward.select())
	restart()