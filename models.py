import os, openvz
from sqlobject import *
sqlhub.processConnection = connectionForURI("sqlite://"+os.path.join(os.getcwd(), "db.sqlite"))

class VM(SQLObject):
	veid = IntCol()
	owner = StringCol(default=None)
	@property
	def vz(self):
		return openvz.VM(self.veid)

if __name__ == "__main__":
	VM.createTable()