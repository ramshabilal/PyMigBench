# coding=utf-8
#
# controller_sensor.py - Sensor controller that manages reading sensors and
#                        creating database entries
#
#  Copyright (C) 2017  Kyle T. Gabriel
#
#  This file is part of Mycodo
#
#  Mycodo is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Mycodo is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Mycodo. If not, see <http://www.gnu.org/licenses/>.
#
#  Contact at kylegabriel.com

import logging
import requests
import threading
import time
import timeit
import RPi.GPIO as GPIO
from lockfile import LockFile

from mycodo_client import DaemonControl
from databases.models import Camera
from databases.models import Conditional
from databases.models import ConditionalActions
from databases.models import PID
from databases.models import Relay
from databases.models import Sensor
from databases.models import SMTP

from devices.tca9548a import TCA9548A
from devices.ads1x15 import ADS1x15Read
from devices.mcp342x import MCP342xRead
from sensors.mycodo_ram import MycodoRam
from sensors.atlas_ph import AtlaspHSensor
from sensors.atlas_pt1000 import AtlasPT1000Sensor
from sensors.am2315 import AM2315Sensor
from sensors.bh1750 import BH1750Sensor
from sensors.bme280 import BME280Sensor
from sensors.bmp180 import BMP180Sensor
from sensors.bmp280 import BMP280Sensor
from sensors.chirp import ChirpSensor
from sensors.dht11 import DHT11Sensor
from sensors.dht22 import DHT22Sensor
from sensors.ds18b20 import DS18B20Sensor
from sensors.htu21d import HTU21DSensor
from sensors.k30 import K30Sensor
from sensors.linux_command import LinuxCommand
from sensors.mh_z16 import MHZ16Sensor
from sensors.mh_z19 import MHZ19Sensor
from sensors.raspi import RaspberryPiCPUTemp
from sensors.raspi_cpuload import RaspberryPiCPULoad
from sensors.raspi_freespace import RaspberryPiFreeSpace
from sensors.tmp006 import TMP006Sensor
from sensors.tsl2561 import TSL2561Sensor
from sensors.tsl2591_sensor import TSL2591Sensor
from sensors.sht1x_7x import SHT1x7xSensor
from sensors.sht2x import SHT2xSensor
from sensors.signal_pwm import PWMInput
from sensors.signal_rpm import RPMInput

from devices.camera import camera_record
from utils.database import db_retrieve_table_daemon
from utils.influx import format_influxdb_data
from utils.influx import read_last_influxdb
from utils.influx import write_influxdb_list
from utils.influx import write_influxdb_value
from utils.send_data import send_email
from utils.system_pi import cmd_output

from config import LIST_DEVICES_I2C


class Measurement:
    """
    Class for holding all measurement values in a dictionary.
    The dictionary is formatted in the following way:

    {'measurement type':measurement value}

    Measurement type: The environmental or physical condition
    being measured, such as 'temperature', or 'pressure'.

    Measurement value: The actual measurement of the condition.
    """

    def __init__(self, raw_data):
        self.rawData = raw_data

    @property
    def values(self):
        return self.rawData


class SensorController(threading.Thread):
    """
    Class for controlling the sensor

    """
    def __init__(self, ready, sensor_id):
        threading.Thread.__init__(self)

        self.logger = logging.getLogger(
            "mycodo.sensor_{id}".format(id=sensor_id))

        self.stop_iteration_counter = 0
        self.thread_startup_timer = timeit.default_timer()
        self.thread_shutdown_timer = 0
        self.ready = ready
        self.lock = {}
        self.measurement = None
        self.updateSuccess = False
        self.sensor_id = sensor_id
        self.control = DaemonControl()
        self.pause_loop = False
        self.verify_pause_loop = True

        self.cond_id = {}
        self.cond_action_id = {}
        self.cond_name = {}
        self.cond_is_activated = {}
        self.cond_if_sensor_period = {}
        self.cond_if_sensor_measurement = {}
        self.cond_if_sensor_edge_select = {}
        self.cond_if_sensor_edge_detected = {}
        self.cond_if_sensor_gpio_state = {}
        self.cond_if_sensor_direction = {}
        self.cond_if_sensor_setpoint = {}
        self.cond_do_relay_id = {}
        self.cond_do_relay_state = {}
        self.cond_do_relay_duration = {}
        self.cond_execute_command = {}
        self.cond_email_notify = {}
        self.cond_do_lcd_id = {}
        self.cond_do_camera_id = {}
        self.cond_timer = {}
        self.smtp_wait_timer = {}

        self.setup_sensor_conditionals()

        sensor = db_retrieve_table_daemon(Sensor, device_id=self.sensor_id)
        self.sensor_sel = sensor
        self.unique_id = sensor.unique_id
        self.i2c_bus = sensor.i2c_bus
        self.location = sensor.location
        self.power_relay_id = sensor.power_relay_id
        self.measurements = sensor.measurements
        self.device = sensor.device
        self.interface = sensor.interface
        self.device_loc = sensor.device_loc
        self.baud_rate = sensor.baud_rate
        self.period = sensor.period
        self.resolution = sensor.resolution
        self.sensitivity = sensor.sensitivity
        self.cmd_command = sensor.cmd_command
        self.cmd_measurement = sensor.cmd_measurement
        self.cmd_measurement_units = sensor.cmd_measurement_units
        self.mux_address_raw = sensor.multiplexer_address
        self.mux_bus = sensor.multiplexer_bus
        self.mux_chan = sensor.multiplexer_channel
        self.adc_chan = sensor.adc_channel
        self.adc_gain = sensor.adc_gain
        self.adc_resolution = sensor.adc_resolution
        self.adc_measure = sensor.adc_measure
        self.adc_measure_units = sensor.adc_measure_units
        self.adc_volts_min = sensor.adc_volts_min
        self.adc_volts_max = sensor.adc_volts_max
        self.adc_units_min = sensor.adc_units_min
        self.adc_units_max = sensor.adc_units_max
        self.adc_inverse_unit_scale = sensor.adc_inverse_unit_scale
        self.sht_clock_pin = sensor.sht_clock_pin
        self.sht_voltage = sensor.sht_voltage

        # Edge detection
        self.switch_edge = sensor.switch_edge
        self.switch_bouncetime = sensor.switch_bouncetime
        self.switch_reset_period = sensor.switch_reset_period

        # PWM and RPM options
        self.weighting = sensor.weighting
        self.rpm_pulses_per_rev = sensor.rpm_pulses_per_rev
        self.sample_time = sensor.sample_time

        # Relay that will activate prior to sensor read
        self.pre_relay_id = sensor.pre_relay_id
        self.pre_relay_duration = sensor.pre_relay_duration
        self.pre_relay_setup = False
        self.next_measurement = time.time()
        self.get_new_measurement = False
        self.trigger_cond = False
        self.measurement_acquired = False
        self.pre_relay_activated = False
        self.pre_relay_timer = time.time()

        relay = db_retrieve_table_daemon(Relay, entry='all')
        for each_relay in relay:  # Check if relay ID actually exists
            if each_relay.id == self.pre_relay_id and self.pre_relay_duration:
                self.pre_relay_setup = True

        smtp = db_retrieve_table_daemon(SMTP, entry='first')
        self.smtp_max_count = smtp.hourly_max
        self.email_count = 0
        self.allowed_to_send_notice = True

        # Convert string I2C address to base-16 int
        if self.device in LIST_DEVICES_I2C:
            self.i2c_address = int(str(self.location), 16)

        # Set up multiplexer if enabled
        if self.device in LIST_DEVICES_I2C and self.mux_address_raw:
            self.mux_address_string = self.mux_address_raw
            self.mux_address = int(str(self.mux_address_raw), 16)
            self.mux_lock = "/var/lock/mycodo_multiplexer_0x{i2c:02X}.pid".format(
                i2c=self.mux_address)
            self.multiplexer = TCA9548A(self.mux_bus, self.mux_address)
        else:
            self.multiplexer = None

        if self.device in ['ADS1x15', 'MCP342x'] and self.location:
            self.adc_lock_file = "/var/lock/mycodo_adc_bus{bus}_0x{i2c:02X}.pid".format(
                bus=self.i2c_bus, i2c=self.i2c_address)

        # Set up edge detection of a GPIO pin
        if self.device == 'EDGE':
            if self.switch_edge == 'rising':
                self.switch_edge_gpio = GPIO.RISING
            elif self.switch_edge == 'falling':
                self.switch_edge_gpio = GPIO.FALLING
            else:
                self.switch_edge_gpio = GPIO.BOTH

        self.lock_multiplexer()

        # Set up analog-to-digital converter
        if self.device == 'ADS1x15':
            self.adc = ADS1x15Read(self.i2c_address, self.i2c_bus,
                                   self.adc_chan, self.adc_gain)
        elif self.device == 'MCP342x':
            self.adc = MCP342xRead(self.i2c_address, self.i2c_bus,
                                   self.adc_chan, self.adc_gain,
                                   self.adc_resolution)
        else:
            self.adc = None

        self.device_recognized = True

        # Set up sensors or devices
        if self.device in ['EDGE', 'ADS1x15', 'MCP342x']:
            self.measure_sensor = None
        elif self.device == 'MYCODO_RAM':
            self.measure_sensor = MycodoRam()
        elif self.device == 'RPiCPULoad':
            self.measure_sensor = RaspberryPiCPULoad()
        elif self.device == 'RPi':
            self.measure_sensor = RaspberryPiCPUTemp()
        elif self.device == 'RPiFreeSpace':
            self.measure_sensor = RaspberryPiFreeSpace(self.location)
        elif self.device == 'AM2302':
            self.measure_sensor = DHT22Sensor(self.sensor_id,
                                              int(self.location))
        elif self.device == 'AM2315':
            self.measure_sensor = AM2315Sensor(self.sensor_id,
                                               self.i2c_bus,
                                               power=self.power_relay_id)
        elif self.device == 'ATLAS_PH_I2C':
            self.measure_sensor = AtlaspHSensor(self.interface,
                                                i2c_address=self.i2c_address,
                                                i2c_bus=self.i2c_bus,
                                                sensor_sel=self.sensor_sel)
        elif self.device == 'ATLAS_PH_UART':
            self.measure_sensor = AtlaspHSensor(self.interface,
                                                device_loc=self.device_loc,
                                                baud_rate=self.baud_rate,
                                                sensor_sel=self.sensor_sel)
        elif self.device == 'ATLAS_PT1000_I2C':
            self.measure_sensor = AtlasPT1000Sensor(self.interface,
                                                    i2c_address=self.i2c_address,
                                                    i2c_bus=self.i2c_bus)
        elif self.device == 'ATLAS_PT1000_UART':
            self.measure_sensor = AtlasPT1000Sensor(self.interface,
                                                    device_loc=self.device_loc,
                                                    baud_rate=self.baud_rate)
        elif self.device == 'BH1750':
            self.measure_sensor = BH1750Sensor(self.i2c_address,
                                               self.i2c_bus,
                                               self.resolution,
                                               self.sensitivity)
        elif self.device == 'BME280':
            self.measure_sensor = BME280Sensor(self.i2c_address,
                                               self.i2c_bus)
        # TODO: BMP is an old designation and will be removed in the future
        elif self.device in ['BMP', 'BMP180']:
            self.measure_sensor = BMP180Sensor(self.i2c_bus)
        elif self.device == 'BMP280':
            self.measure_sensor = BMP280Sensor(self.i2c_address,
                                               self.i2c_bus)
        elif self.device == 'CHIRP':
            self.measure_sensor = ChirpSensor(self.i2c_address,
                                              self.i2c_bus)
        elif self.device == 'DS18B20':
            self.measure_sensor = DS18B20Sensor(self.location)
        elif self.device == 'DHT11':
            self.measure_sensor = DHT11Sensor(self.sensor_id,
                                              int(self.location),
                                              power=self.power_relay_id)
        elif self.device == 'DHT22':
            self.measure_sensor = DHT22Sensor(self.sensor_id,
                                              int(self.location),
                                              power=self.power_relay_id)
        elif self.device == 'HTU21D':
            self.measure_sensor = HTU21DSensor(self.i2c_bus)
        elif self.device == 'K30_UART':
            self.measure_sensor = K30Sensor(self.device_loc,
                                            baud_rate=self.baud_rate)
        elif self.device == 'MH_Z16_I2C':
            self.measure_sensor = MHZ16Sensor(self.interface,
                                              i2c_address=self.i2c_address,
                                              i2c_bus=self.i2c_bus)
        elif self.device == 'MH_Z16_UART':
            self.measure_sensor = MHZ16Sensor(self.interface,
                                              device_loc=self.device_loc,
                                              baud_rate=self.baud_rate)
        elif self.device == 'MH_Z19_UART':
            self.measure_sensor = MHZ19Sensor(self.device_loc,
                                              baud_rate=self.baud_rate)
        elif self.device == 'SHT1x_7x':
            self.measure_sensor = SHT1x7xSensor(int(self.location),
                                                self.sht_clock_pin,
                                                self.sht_voltage)
        elif self.device == 'SHT2x':
            self.measure_sensor = SHT2xSensor(self.i2c_address,
                                              self.i2c_bus)
        elif self.device == 'SIGNAL_PWM':
            self.measure_sensor = PWMInput(int(self.location),
                                           self.weighting,
                                           self.sample_time)
        elif self.device == 'SIGNAL_RPM':
            self.measure_sensor = RPMInput(int(self.location),
                                           self.weighting,
                                           self.rpm_pulses_per_rev,
                                           self.sample_time)
        elif self.device == 'TMP006':
            self.measure_sensor = TMP006Sensor(self.i2c_address,
                                               self.i2c_bus)
        elif self.device == 'TSL2561':
            self.measure_sensor = TSL2561Sensor(self.i2c_address,
                                                self.i2c_bus)
        elif self.device == 'TSL2591':
            self.measure_sensor = TSL2591Sensor(self.i2c_address,
                                                self.i2c_bus)
        elif self.device == 'LinuxCommand':
            self.measure_sensor = LinuxCommand(self.cmd_command,
                                               self.cmd_measurement)
        else:
            self.device_recognized = False
            self.logger.debug("Device '{device}' not recognized".format(
                device=self.device))
            raise Exception("'{device}' is not a valid device type.".format(
                device=self.device))

        self.unlock_multiplexer()

        self.edge_reset_timer = time.time()
        self.sensor_timer = time.time()
        self.running = False
        self.lastUpdate = None

    def run(self):
        try:
            self.running = True
            self.logger.info("Activated in {:.1f} ms".format(
                (timeit.default_timer() - self.thread_startup_timer) * 1000))
            self.ready.set()

            # Set up edge detection
            if self.device == 'EDGE':
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(int(self.location), GPIO.IN)
                GPIO.add_event_detect(int(self.location),
                                      self.switch_edge_gpio,
                                      callback=self.edge_detected,
                                      bouncetime=self.switch_bouncetime)

            while self.running:
                # Pause loop to modify conditional statements.
                # Prevents execution of conditional while variables are
                # being modified.
                if self.pause_loop:
                    self.verify_pause_loop = True
                    while self.pause_loop:
                        time.sleep(0.1)

                if self.device not in ['EDGE']:
                    # Signal that a measurement needs to be obtained
                    if time.time() > self.next_measurement and not self.get_new_measurement:
                        self.get_new_measurement = True
                        self.trigger_cond = True
                        self.next_measurement = time.time() + self.period

                    # if signaled and a pre relay is set up correctly, turn the
                    # relay on for the set duration
                    if (self.get_new_measurement and
                            self.pre_relay_setup and
                            not self.pre_relay_activated):
                        relay_on = threading.Thread(
                            target=self.control.relay_on,
                            args=(self.pre_relay_id,
                                  self.pre_relay_duration,))
                        relay_on.start()
                        self.pre_relay_activated = True
                        self.pre_relay_timer = time.time() + self.pre_relay_duration

                    # If using a pre relay, wait for it to complete before
                    # querying the sensor for a measurement
                    if self.get_new_measurement:
                        if ((self.pre_relay_setup and
                                self.pre_relay_activated and
                                time.time() < self.pre_relay_timer) or
                                not self.pre_relay_setup):
                            # Get measurement(s) from sensor
                            self.update_measure()
                            # Add measurement(s) to influxdb
                            self.add_measure_influxdb()
                            self.pre_relay_activated = False
                            self.get_new_measurement = False

                for each_cond_id in self.cond_id:
                    if self.cond_is_activated[each_cond_id]:
                        # Check sensor conditional if it has been activated
                        if (self.device in ['EDGE'] and
                                self.cond_if_sensor_edge_select[each_cond_id] == 'state' and
                                time.time() > self.cond_timer[each_cond_id]):
                            # Inputs that are triggered (switch, reed, hall, etc.)
                            self.cond_timer[each_cond_id] = time.time() + self.cond_if_sensor_period[each_cond_id]
                            self.check_conditionals(each_cond_id)
                        elif ((not self.cond_timer[each_cond_id] and self.trigger_cond) or
                                time.time() > self.cond_timer[each_cond_id]):
                            # Inputs that are not triggered (sensors)
                            self.cond_timer[each_cond_id] = time.time() + self.cond_if_sensor_period[each_cond_id]
                            self.check_conditionals(each_cond_id)

                self.trigger_cond = False

                time.sleep(0.1)

            self.running = False

            if self.device == 'EDGE':
                GPIO.setmode(GPIO.BCM)
                GPIO.cleanup(int(self.location))

            self.logger.info("Deactivated in {:.1f} ms".format(
                (timeit.default_timer() - self.thread_shutdown_timer) * 1000))
        except requests.ConnectionError:
            self.logger.error("Could not connect to influxdb. Check that it "
                              "is running and accepting connections")
        except Exception as except_msg:
            self.logger.exception("Error: {err}".format(
                err=except_msg))

    def add_measure_influxdb(self):
        """
        Add a measurement entries to InfluxDB

        :rtype: None
        """
        if self.updateSuccess:
            data = []
            for each_measurement, each_value in self.measurement.values.items():
                data.append(format_influxdb_data(self.unique_id,
                                                 each_measurement,
                                                 each_value))
            write_db = threading.Thread(
                target=write_influxdb_list,
                args=(data,))
            write_db.start()

    def check_conditionals(self, cond_id):
        """
        Check if any sensor conditional statements are activated and
        execute their actions if the conditional is true.

        For example, if measured temperature is above 30C, notify me@gmail.com

        :rtype: None

        :param cond_id: ID of conditional to check
        :type cond_id: str
        """
        logger_cond = logging.getLogger("mycodo.sensor_cond_{id}".format(
            id=cond_id))
        attachment_file = False
        attachment_type = False

        cond = db_retrieve_table_daemon(
            Conditional, device_id=cond_id, entry='first')

        message = u"[Sensor Conditional: {name} ({id})]".format(
            name=cond.name,
            id=cond_id)

        if cond.if_sensor_direction:
            last_measurement = self.get_last_measurement(
                cond.if_sensor_measurement)
            if (last_measurement and
                    ((cond.if_sensor_direction == 'above' and
                        last_measurement > cond.if_sensor_setpoint) or
                     (cond.if_sensor_direction == 'below' and
                        last_measurement < cond.if_sensor_setpoint))):

                message += u" {meas}: {value} ".format(
                    meas=cond.if_sensor_measurement,
                    value=last_measurement)
                if cond.if_sensor_direction == 'above':
                    message += "(>"
                elif cond.if_sensor_direction == 'below':
                    message += "(<"
                message += u" {sp} set value).".format(
                    sp=cond.if_sensor_setpoint)
            else:
                logger_cond.debug("Last measurement not found")
                return 1
        elif cond.if_sensor_edge_detected:
            if cond.if_sensor_edge_select == 'edge':
                message += u" {edge} Edge Detected.".format(
                    edge=cond.if_sensor_edge_detected)
            elif cond.if_sensor_edge_select == 'state':
                if GPIO.input(int(self.location)) == cond.if_sensor_gpio_state:
                    message += u" {state} GPIO State Detected.".format(
                        state=cond.if_sensor_gpio_state)
                else:
                    return 0

        cond_actions = db_retrieve_table_daemon(ConditionalActions)
        cond_actions = cond_actions.filter(
            ConditionalActions.conditional_id == cond_id).all()

        for cond_action in cond_actions:
            message += u" Conditional Action ({id}): {do_action}.".format(
                id=cond_action.id, do_action=cond_action.do_action)

            # Actuate relay
            if (cond_action.do_relay_id and
                    cond_action.do_relay_state in ['on', 'off']):
                message += u" Turn relay {id} {state}".format(
                        id=cond_action.do_relay_id,
                        state=cond_action.do_relay_state)
                if (cond_action.do_relay_state == 'on' and
                        cond_action.do_relay_duration):
                    message += u" for {sec} seconds".format(
                        sec=cond_action.do_relay_duration)
                message += "."
                relay_on_off = threading.Thread(
                    target=self.control.relay_on_off,
                    args=(cond_action.do_relay_id,
                          cond_action.do_relay_state,),
                    kwargs={'duration': cond_action.do_relay_duration})
                relay_on_off.start()

            # Execute command in shell
            elif cond_action.do_action == 'command':
                message += u" Execute '{com}' ".format(
                        com=cond_action.do_action_string)

                command_str = cond_action.do_action_string
                for each_measurement, each_value in self.measurement.values.items():
                    command_str = command_str.replace(
                        "((input_{var}))".format(var=each_measurement), str(each_value))
                command_str = command_str.replace(
                    "((input_location))", str(self.location))
                command_str = command_str.replace(
                    "((input_period))", str(self.cond_if_sensor_period[cond_id]))
                _, _, cmd_status = cmd_output(command_str)

                message += u"(Status: {stat}).".format(stat=cmd_status)

            # Capture photo
            elif cond_action.do_action in ['photo', 'photo_email']:
                message += u"  Capturing photo with camera ({id}).".format(
                    id=cond_action.do_camera_id)
                camera_still = db_retrieve_table_daemon(
                    Camera, device_id=cond_action.do_camera_id)
                attachment_file = camera_record('photo', camera_still)

            # Capture video
            elif cond_action.do_action in ['video', 'video_email']:
                message += u"  Capturing video with camera ({id}).".format(
                    id=cond_action.do_camera_id)
                camera_stream = db_retrieve_table_daemon(
                    Camera, device_id=cond_action.do_camera_id)
                attachment_file = camera_record(
                    'video', camera_stream,
                    duration_sec=cond_action.do_camera_duration)

            # Activate PID controller
            elif cond_action.do_action == 'activate_pid':
                message += u" Activate PID ({id}).".format(
                    id=cond_action.do_pid_id)
                pid = db_retrieve_table_daemon(
                    PID, device_id=cond_action.do_pid_id, entry='first')
                if pid.is_activated:
                    message += u" Notice: PID is already active!"
                else:
                    activate_pid = threading.Thread(
                        target=self.control.controller_activate,
                        args=('PID',
                              cond_action.do_pid_id,))
                    activate_pid.start()

            # Deactivate PID controller
            elif cond_action.do_action == 'deactivate_pid':
                message += u" Deactivate PID ({id}).".format(
                    id=cond_action.do_pid_id)
                pid = db_retrieve_table_daemon(
                    PID, device_id=cond_action.do_pid_id, entry='first')
                if not pid.is_activated:
                    message += u" Notice: PID is already inactive!"
                else:
                    deactivate_pid = threading.Thread(
                        target=self.control.controller_deactivate,
                        args=('PID',
                              cond_action.do_pid_id,))
                    deactivate_pid.start()

            elif cond_action.do_action in ['email',
                                           'photo_email',
                                           'video_email']:
                if (self.email_count >= self.smtp_max_count and
                        time.time() < self.smtp_wait_timer[cond_id]):
                    self.allowed_to_send_notice = False
                else:
                    if time.time() > self.smtp_wait_timer[cond_id]:
                        self.email_count = 0
                        self.smtp_wait_timer[cond_id] = time.time() + 3600
                    self.allowed_to_send_notice = True
                self.email_count += 1

                # If the emails per hour limit has not been exceeded
                if self.allowed_to_send_notice:
                    message += u" Notify {email}.".format(
                        email=cond_action.do_action_string)
                    # attachment_type != False indicates to
                    # attach a photo or video
                    if cond_action.do_action == 'photo_email':
                        message += u" Photo attached to email."
                        attachment_type = 'still'
                    elif cond_action.do_action == 'video_email':
                        message += u" Video attached to email."
                        attachment_type = 'video'

                    smtp = db_retrieve_table_daemon(SMTP, entry='first')
                    send_email(smtp.host, smtp.ssl, smtp.port,
                               smtp.user, smtp.passw, smtp.email_from,
                               cond_action.do_action_string, message,
                               attachment_file, attachment_type)
                else:
                    logger_cond.debug(
                        "Wait {sec:.0f} seconds to email again.".format(
                            sec=self.smtp_wait_timer[cond_id]-time.time()))

            elif cond_action.do_action == 'flash_lcd':
                message += u" Flashing LCD ({id}).".format(
                    id=cond_action.do_lcd_id)
                start_flashing = threading.Thread(
                    target=self.control.flash_lcd,
                    args=(cond_action.do_lcd_id, 1,))
                start_flashing.start()

        logger_cond.debug(message)

    def lock_multiplexer(self):
        """ Acquire a multiplexer lock """
        if self.multiplexer:
            (lock_status,
             lock_response) = self.setup_lock(self.mux_address,
                                              self.mux_bus,
                                              self.mux_lock)
            if not lock_status:
                self.logger.warning(
                    "Could not acquire lock for multiplexer. Error: "
                    "{err}".format(err=lock_response))
                self.updateSuccess = False
                return 1
            self.logger.debug(
                "Setting multiplexer ({add}) to channel {chan}".format(
                    add=self.mux_address_string,
                    chan=self.mux_chan))
            # Set multiplexer channel
            (multiplexer_status,
             multiplexer_response) = self.multiplexer.setup(self.mux_chan)
            if not multiplexer_status:
                self.logger.warning(
                    "Could not set channel with multiplexer at address {add}."
                    " Error: {err}".format(
                        add=self.mux_address_string,
                        err=multiplexer_response))
                self.updateSuccess = False
                return 1

    def unlock_multiplexer(self):
        """ Remove a multiplexer lock """
        if self.multiplexer:
            self.release_lock(self.mux_address, self.mux_bus, self.mux_lock)

    def update_measure(self):
        """
        Retrieve measurement from sensor

        :return: None if success, 0 if fail
        :rtype: int or None
        """
        measurements = None

        if not self.device_recognized:
            self.logger.debug("Device not recognized: {device}".format(
                device=self.device))
            self.updateSuccess = False
            return 1

        self.lock_multiplexer()

        if self.adc:
            try:
                # Acquire a lock for ADC
                (lock_status,
                 lock_response) = self.setup_lock(self.i2c_address,
                                                  self.i2c_bus,
                                                  self.adc_lock_file)
                if not lock_status:
                    self.logger.warning(
                        "Could not acquire lock for multiplexer. Error: "
                        "{err}".format(err=lock_response))
                    self.updateSuccess = False
                    return 1

                # Get measurement from ADC
                measurements = self.adc.next()
                if measurements is not None:
                    # Get the voltage difference between min and max volts
                    diff_voltage = abs(self.adc_volts_max - self.adc_volts_min)
                    # Ensure the voltage stays within the min/max bounds
                    if measurements['voltage'] < self.adc_volts_min:
                        measured_voltage = self.adc_volts_min
                    elif measurements['voltage'] > self.adc_volts_max:
                        measured_voltage = self.adc_volts_max
                    else:
                        measured_voltage = measurements['voltage']
                    # Calculate the percentage of the voltage difference
                    percent_diff = ((measured_voltage - self.adc_volts_min) /
                                    diff_voltage)

                    # Get the units difference between min and max units
                    diff_units = abs(self.adc_units_max - self.adc_units_min)
                    # Calculate the measured units from the percent difference
                    if self.adc_inverse_unit_scale:
                        converted_units = (self.adc_units_max -
                                           (diff_units * percent_diff))
                    else:
                        converted_units = (self.adc_units_min +
                                           (diff_units * percent_diff))
                    # Ensure the units stay within the min/max bounds
                    if converted_units < self.adc_units_min:
                        measurements[self.adc_measure] = self.adc_units_min
                    elif converted_units > self.adc_units_max:
                        measurements[self.adc_measure] = self.adc_units_max
                    else:
                        measurements[self.adc_measure] = converted_units
            except Exception as except_msg:
                self.logger.exception(
                    "Error while attempting to read adc: {err}".format(
                        err=except_msg))
            finally:
                self.release_lock(self.i2c_address,
                                  self.i2c_bus,
                                  self.adc_lock_file)
        else:
            try:
                # Get measurement from sensor
                measurements = self.measure_sensor.next()
                # Reset StopIteration counter on successful read
                if self.stop_iteration_counter:
                    self.stop_iteration_counter = 0
            except StopIteration:
                self.stop_iteration_counter += 1
                # Notify after 3 consecutive errors. Prevents filling log
                # with many one-off errors over long periods of time
                if self.stop_iteration_counter > 2:
                    self.stop_iteration_counter = 0
                    self.logger.error(
                        "StopIteration raised. Possibly could not read "
                        "sensor. Ensure it's connected properly and "
                        "detected.")
            except Exception as except_msg:
                self.logger.exception(
                    "Error while attempting to read sensor: {err}".format(
                        err=except_msg))

        self.unlock_multiplexer()

        if self.device_recognized and measurements is not None:
            self.measurement = Measurement(measurements)
            self.updateSuccess = True
        else:
            self.updateSuccess = False

        self.lastUpdate = time.time()

    def setup_lock(self, i2c_address, i2c_bus, lockfile):
        execution_timer = timeit.default_timer()
        try:
            self.lock[lockfile] = LockFile(lockfile)
            while not self.lock[lockfile].i_am_locking():
                try:
                    self.logger.debug(
                        "[Locking bus-{bus} 0x{i2c:02X}] Acquiring Lock: "
                        "{lock}".format(
                            bus=i2c_bus,
                            i2c=i2c_address,
                            lock=self.lock[lockfile].path))
                    # wait up to 60 seconds
                    self.lock[lockfile].acquire(timeout=60)
                except Exception as e:
                    self.logger.error(
                        "{cls} raised an exception: {err}".format(
                            cls=type(self).__name__, err=e))
                    self.logger.exception(
                        "[Locking bus-{bus} 0x{i2c:02X}] Waited 60 seconds. "
                        "Breaking lock to acquire {lock}".format(
                            bus=i2c_bus,
                            i2c=i2c_address,
                            lock=self.lock[lockfile].path))
                    self.lock[lockfile].break_lock()
                    self.lock[lockfile].acquire()
            self.logger.debug(
                "[Locking bus-{bus} 0x{i2c:02X}] Acquired Lock: "
                "{lock}".format(
                    bus=i2c_bus,
                    i2c=i2c_address,
                    lock=self.lock[lockfile].path))
            self.logger.debug(
                "[Locking bus-{bus} 0x{i2c:02X}] Executed in {ms:.1f} ms".format(
                    bus=i2c_bus,
                    i2c=i2c_address,
                    ms=(timeit.default_timer()-execution_timer)*1000))
            return 1, "Success"
        except Exception as msg:
            return 0, "Multiplexer Fail: {}".format(msg)

    def release_lock(self, i2c_address, i2c_bus, lockfile):
        self.logger.debug(
            "[Locking bus-{bus} 0x{i2c:02X}] Releasing Lock: {lock}".format(
                bus=i2c_bus, i2c=i2c_address, lock=lockfile))
        self.lock[lockfile].release()

    def get_last_measurement(self, measurement_type):
        """
        Retrieve the latest sensor measurement

        :return: The latest sensor value or None if no data available
        :rtype: float or None

        :param measurement_type: Environmental condition of a sensor (e.g.
            temperature, humidity, pressure, etc.)
        :type measurement_type: str
        """
        last_measurement = read_last_influxdb(
            self.unique_id, measurement_type, int(self.period * 1.5))

        if last_measurement:
            last_value = last_measurement[1]
            return last_value
        else:
            return None

    def edge_detected(self, pin):
        gpio_state = GPIO.input(int(self.location))
        if time.time() > self.edge_reset_timer:
            self.edge_reset_timer = time.time()+self.switch_reset_period
            if (self.switch_edge == 'rising' or
                    (self.switch_edge == 'both' and gpio_state)):
                rising_or_falling = 1  # Rising edge detected
            else:
                rising_or_falling = -1  # Falling edge detected
            write_db = threading.Thread(
                target=write_influxdb_value,
                args=(self.unique_id, 'edge', rising_or_falling,))
            write_db.start()

            # Check sensor conditionals
            for each_cond_id in self.cond_id:
                if ((self.cond_is_activated[each_cond_id] and
                     self.cond_if_sensor_edge_select[each_cond_id] == 'edge') and
                        ((self.cond_if_sensor_edge_detected[each_cond_id] == 'rising' and
                          rising_or_falling == 1) or
                         (self.cond_if_sensor_edge_detected[each_cond_id] == 'falling' and
                          rising_or_falling == -1) or
                         self.cond_if_sensor_edge_detected[each_cond_id] == 'both')):
                    self.check_conditionals(each_cond_id)

    def setup_sensor_conditionals(self, cond_mod='setup'):
        # Signal to pause the main loop and wait for verification
        self.pause_loop = True
        while not self.verify_pause_loop:
            time.sleep(0.1)

        self.cond_id = {}
        self.cond_action_id = {}
        self.cond_name = {}
        self.cond_is_activated = {}
        self.cond_if_sensor_period = {}
        self.cond_if_sensor_measurement = {}
        self.cond_if_sensor_edge_select = {}
        self.cond_if_sensor_edge_detected = {}
        self.cond_if_sensor_gpio_state = {}
        self.cond_if_sensor_direction = {}
        self.cond_if_sensor_setpoint = {}

        sensor_conditional = db_retrieve_table_daemon(
            Conditional)
        sensor_conditional = sensor_conditional.filter(
            Conditional.sensor_id == self.sensor_id)
        sensor_conditional = sensor_conditional.filter(
            Conditional.is_activated == True).all()

        if cond_mod == 'setup':
            self.cond_timer = {}
            self.smtp_wait_timer = {}
        elif cond_mod == 'add':
            self.logger.debug("Added Conditional")
        elif cond_mod == 'del':
            self.logger.debug("Deleted Conditional")
        elif cond_mod == 'mod':
            self.logger.debug("Modified Conditional")
        else:
            return 1

        for each_cond in sensor_conditional:
            if cond_mod == 'setup':
                self.logger.info(
                    "Activated Conditional ({id})".format(id=each_cond.id))
            self.cond_id[each_cond.id] = each_cond.id
            self.cond_is_activated[each_cond.id] = each_cond.is_activated
            self.cond_if_sensor_period[each_cond.id] = each_cond.if_sensor_period
            self.cond_if_sensor_measurement[each_cond.id] = each_cond.if_sensor_measurement
            self.cond_if_sensor_edge_select[each_cond.id] = each_cond.if_sensor_edge_select
            self.cond_if_sensor_edge_detected[each_cond.id] = each_cond.if_sensor_edge_detected
            self.cond_if_sensor_gpio_state[each_cond.id] = each_cond.if_sensor_gpio_state
            self.cond_if_sensor_direction[each_cond.id] = each_cond.if_sensor_direction
            self.cond_if_sensor_setpoint[each_cond.id] = each_cond.if_sensor_setpoint
            self.cond_timer[each_cond.id] = time.time() + each_cond.if_sensor_period
            self.smtp_wait_timer[each_cond.id] = time.time() + 3600

        self.pause_loop = False
        self.verify_pause_loop = False

    def is_running(self):
        return self.running

    def stop_controller(self):
        self.thread_shutdown_timer = timeit.default_timer()
        if self.device not in ['EDGE', 'ADS1x15', 'MCP342x']:
            self.measure_sensor.stop_sensor()
        self.running = False
