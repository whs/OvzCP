import os, openvz
from sqlobject import *
sqlhub.processConnection = connectionForURI("sqlite://"+os.path.join(os.getcwd(), "db.sqlite")+"?debug=true")

class User(SQLObject):
	email = StringCol()
	credit = FloatCol()
	vm = SQLMultipleJoin('VM')
	def __str__(self):
		return self.email

class VM(SQLObject):
	veid = IntCol()
	user = ForeignKey('User')
	varnishBackend = SQLMultipleJoin('VarnishBackend')
	portForward = SQLMultipleJoin('PortForward')
	@property
	def vz(self):
		return openvz.VM(self.veid)

class PortForward(SQLObject):
	iface = StringCol()
	vm = ForeignKey('VM')
	port = IntCol()
	outport = IntCol()

class VarnishBackend(SQLObject):
	name = StringCol()
	vm = ForeignKey('VM')
	port = IntCol()
	cond = SQLMultipleJoin('VarnishCond')

class VarnishCond(SQLObject):
	hostname = StringCol()
	subdomain = BoolCol(default=True)
	varnishBackend = ForeignKey('VarnishBackend')
	@property
	def backend(self):
		return self.varnishBackend

if __name__ == "__main__":
	User.createTable(True)
	VM.createTable(True)
	VarnishBackend.createTable(True)
	VarnishCond.createTable(True)
	PortForward.createTable(True)