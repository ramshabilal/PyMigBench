# coding=utf-8

from lockfile import LockFile
import logging
import serial
import time
from .base_sensor import AbstractSensor

from sensorutils import is_device


class MHZ19Sensor(AbstractSensor):
    """ A sensor support class that monitors the MH-Z19's CO2 concentration """

    def __init__(self, device_loc, baud_rate=9600):
        super(MHZ19Sensor, self).__init__()
        self.logger = logging.getLogger(
            "mycodo.sensors.mhz19.{dev}".format(dev=device_loc.replace('/', '')))
        self.k30_lock_file = None
        self._co2 = 0

        # Check if device is valid
        self.serial_device = is_device(device_loc)
        if self.serial_device:
            try:
                self.ser = serial.Serial(self.serial_device,
                                         baudrate=baud_rate,
                                         timeout=1)
                self.k30_lock_file = "/var/lock/sen-mhz19-{}".format(device_loc.replace('/', ''))
            except serial.SerialException:
                self.logger.exception('Opening serial')
        else:
            self.logger.error(
                'Could not open "{dev}". '
                'Check the device location is correct.'.format(
                    dev=device_loc))

    def __repr__(self):
        """  Representation of object """
        return "<{cls}(co2={co2})>".format(
            cls=type(self).__name__,
            co2="{0:.2f}".format(self._co2))

    def __str__(self):
        """ Return CO2 information """
        return "CO2: {co2}".format(co2="{0:.2f}".format(self._co2))

    def __iter__(self):  # must return an iterator
        """ MH-Z19 iterates through live CO2 readings """
        return self

    def next(self):
        """ Get next CO2 reading """
        if self.read():  # raised an error
            raise StopIteration  # required
        return dict(co2=float('{0:.2f}'.format(self._co2)))

    def info(self):
        conditions_measured = [
            ("CO2", "co2", "float", "0.00", self._co2, self.co2)
        ]
        return conditions_measured

    @property
    def co2(self):
        """ CO2 concentration in ppmv """
        if not self._co2:  # update if needed
            self.read()
        return self._co2

    def get_measurement(self):
        """ Gets the MH-Z19's CO2 concentration in ppmv via UART"""
        self._co2 = None
        self.ser.flushInput()
        time.sleep(1)
        self.ser.write("\xff\x01\x86\x00\x00\x00\x00\x00\x79")
        time.sleep(.01)
        resp = self.ser.read(9)
        if len(resp) != 0:
            high = ord(resp[2])
            low = ord(resp[3])
            co2 = (high * 256) + low
            return co2
        return None

    def read(self):
        """
        Takes a reading from the MH-Z19 and updates the self._co2 value

        :returns: None on success or 1 on error
        """
        if not self.serial_device:  # Don't measure if device isn't validated
            return None

        lock = LockFile(self.k30_lock_file)
        try:
            # Acquire lock on MHZ19 to ensure more than one read isn't
            # being attempted at once.
            while not lock.i_am_locking():
                try:  # wait 60 seconds before breaking lock
                    lock.acquire(timeout=60)
                except Exception as e:
                    self.logger.error(
                        "{cls} 60 second timeout, {lock} lock broken: "
                        "{err}".format(
                            cls=type(self).__name__,
                            lock=self.k30_lock_file,
                            err=e))
                    lock.break_lock()
                    lock.acquire()
            self._co2 = self.get_measurement()
            lock.release()
            if self._co2 is None:
                return 1
            return  # success - no errors
        except Exception as e:
            self.logger.error(
                "{cls} raised an exception when taking a reading: "
                "{err}".format(cls=type(self).__name__, err=e))
            lock.release()
            return 1
