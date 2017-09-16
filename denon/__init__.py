#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
# todo
# put your name and email here and delete these two todo lines
#  Copyright 2016 Sebastian Sudholt      sebastian.sudholt@tu-dortmund.de
#########################################################################
#  This file is part of SmartHomeNG.   
#
#  Plugin for controlling Denon devices over a telnet connection.
#  The complete Denon API reference can be found here:
#  http://openrb.com/wp-content/uploads/2012/02/AVR3312CI_AVR3312_PROTOCOL_V7.6.0.pdf
#
#  SmartHomeNG is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  SmartHomeNG is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with SmartHomeNG. If not, see <http://www.gnu.org/licenses/>.
#
#########################################################################

import logging
import queue
import socket
import threading
import time

from lib.model.smartplugin import SmartPlugin

def mv_to_avr(mv_val):
    '''
    convert a master volume val of type float into the correct string value to
    be sent to the Denon AVR
    
    :param mv_val: (float) master volume value to be transformed
    '''
    decimal = mv_val - int(mv_val)
    # round to the next .5
    decimal = round(decimal *2) / 2
    if decimal == 0:
        return str(int(mv_val))
    else:
        return str(int(mv_val) + '5')

def mv_from_avr(mv_val):
    '''
    convert a master volume string received from the Denon device
    to a float 
    '''
    if len(mv_val) == 2:
        return float(mv_val)
    else:
        return float(mv_val[:2]) + 0.5

class DenonAVR(SmartPlugin):
    """
    Main class of the DenonAVR Plugin.
    """
    ALLOW_MULTIINSTANCE = True
    PLUGIN_VERSION = '1.3.0'
    
    # dictionary mapping input channels to names and back
    _si_map = {'MPLAY': 'Media Player', 'Media Player': 'MPLAY',               
               'SAT/CBL': 'Satellite/Cable', 'Satellite/Cable': 'SAT/CBL',
               'GAME': 'Game', 'Game': 'GAME',
               'BD': 'Blu-ray Player', 'Blu-ray Player': 'BD',
               'PHONO': 'Phonograph', 'Phonograph': 'PHONO',
               'TV': 'TV', 'DVD': 'DVD', 'CD': 'CD', 'DVR': 'DVR'}
    # dictionary containing the possible denon_avr_attribute names
    # and the corresponding command from the Denon API    
    _cmd_dict = dict(power=dict(cmd='PW',
                                type='bool',
                                to_avr=lambda x: 'ON' if x else 'STANDBY',
                                from_avr=lambda x: SmartPlugin.to_bool(x, default=False)),
                     input=dict(cmd='SI',
                                type='str',
                                to_avr=lambda x: DenonAVR._si_map[x],
                                from_avr=lambda x: DenonAVR._si_map[x]),
                     volume=dict(cmd='MV',
                                 type='num',
                                 to_avr=mv_to_avr,
                                 from_avr=mv_from_avr),
                     mute=dict(cmd='MU',
                               type='bool',
                               to_avr=lambda x: 'ON' if x else 'OFF',
                               from_avr=SmartPlugin.to_bool))
    # create a reverse dictionary for the commands for easy look up    
    _inv_cmd_dict = {v['cmd']: k for k, v in _cmd_dict.items()}
    
    def __init__(self, sh, host, port=23, recv_sleep=0.1):
        """
        Initalizes the plugin. The parameters describe for this method are pulled from the entry in plugin.conf.

        :param sh:  The instance of the smarthome object, save it for later references
        """
        # attention:
        # if your plugin runs standalone, sh will likely be None so do not rely on it later or check it within your code
        self._sh = sh
        self.logger = logging.getLogger(__name__)     # get a unique logger for the plugin and provide it internally
        # check if the IP address is valid
        if not self.is_ip(host):
            self.logger.fatal('The supplied host attribute is not an IP address!')
        if not self.is_int(port):
            self.logger.fatal('Port must be an integer')
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)        
        self.address = (host, port)
        self.max_volume = 99.0
        self.item_dicts = {elem: [] for elem in list(self._cmd_dict.keys())}
        self.recv_thread = threading.Thread(target=self._recv_loop,
                                            kwargs=dict(recv_sleep=recv_sleep))
        self.recv_lock = threading.Lock()
    
    def request_info(self, denon_attribute):
        """
        Request the current information available for the given command
        """
        # obtain the Denon API command from the original command name
        cmd = self._cmd_dict[denon_attribute]['cmd']
        telnet_req = '%s?\r' % cmd
        # acquire the recv lock as we want to listen for an answer from the receiver
        self.recv_lock.acquire()
        bytes_sent = self.sock.send(telnet_req.encode())
        if len(telnet_req) != bytes_sent:
            self.logger.error('Sending request \'%s\' yielded an error', telnet_req)
            return None
        # the AVR should answer within 200ms
        # if not, something went wrong
        time.sleep(0.2)
        try:
            response = self.sock.recv(2048).decode()
            response = self._parse_response(response)
            if len(response) == 0:
                # no real blocking error here, but we want to trigger the exception case
                raise BlockingIOError
        except BlockingIOError:
            self.logger.error('The command \'%s\' did not yield any response', telnet_req)
            return None
        else:
            self.logger.debug('Reponse for \'%s\': \'%s\'', telnet_req.strip(), str(response))
        finally:
            self.recv_lock.release()
        return response
    
    def send_command(self, cmd, value):
        '''
        send a command to the Denon AVR
        
        :param cmd: the command to be sent. Can be any of the commands defined as keys in the _cmd_dict
        :param value: the value to the command. Must be of the correct type specified in the dict
        :return True if sending was successful, False otherwise
        '''
        # build telnet string
        telnet_cmd = self._cmd_dict[cmd]['cmd'] + self._cmd_dict[cmd]['to_avr'](value) + '\r'
        self.logger.debug('Sending telnet command: %s', telnet_cmd)        
        bytes_sent = self.sock.send(telnet_cmd.encode())
        if bytes_sent != len(telnet_cmd):
            self.logger.error('Sending command \'%s\' failed', telnet_cmd)
            return False
        else:
            return True

    def run(self):
        """
        Connect the socket and start the recv thread
        """
        try:
            self.sock.connect(self.address)
            self.logger.debug('Connected to %s on port %d', *self.address)
            # set timeout to zero so recv does not block
            self.sock.settimeout(0)            
        except:
            self.logger.error('Could not connect to %s on port %d', *self.address)
            self.alive = False
        else:
            self.alive = True
            self.recv_thread.start()
        # retrieve the current status for all registered items and update them
        response_dict = dict()
        for key, value in self.item_dicts.items():
            if len(value) != 0:
                resp = self.request_info(denon_attribute=key)
                response_dict.update(resp)
        self._update_items_from_response_dict(response_dict)


    def stop(self):
        """
        Stop method for the plugin
        """
        self.logger.debug("stop method called")
        self.alive = False
        self.recv_thread.join()
        self.sock.close()

    def parse_item(self, item):
        '''
        Default plugin parse_item method. Is called when the plugin is initialized.
        The plugin can, corresponding to its attribute keywords, decide what to do with
        the item in future, like adding it to an internal array for future reference

        :param item:    The item to process.
        :return:        If the plugin needs to be informed of an items change you should return a call back function
                        like the function update_item down below. An example when this is needed is the knx plugin
                        where parse_item returns the update_item function when the attribute knx_send is found.
                        This means that when the items value is about to be updated, the call back function is called
                        with the item, caller, source and dest as arguments and in case of the knx plugin the value
                        can be sent to the knx with a knx write function within the knx plugin.

        '''
        # register all items with the denon_avr_attribute
        if self.has_iattr(item.conf, 'denon_avr_attribute'):
            self.logger.debug('Registering item: {0}'.format(item))
            denon_attrib = self.get_iattr_value(item.conf, 'denon_avr_attribute') 
            if denon_attrib not in list(self._cmd_dict.keys()):
                self.logger.error('The denon_avr_attribute \'%s\' is unknown', denon_attrib)
                return None
            if item.type() != self._cmd_dict[denon_attrib]['type']:
                self.logger.error('The denon_avr_attribute \'%s\' has illegal type %s (should be %s)',
                                  denon_attrib, item.type(),
                                  str(self._cmd_dict[denon_attrib]['type']))
                return None
            
            self.item_dicts[denon_attrib].append(item)
            return self.update_item_callback

    def update_item_callback(self, item, caller=None, source=None, dest=None):
        '''
        Function to be called whenever an item is updated
        the DenonAVR class listens to

        :param item: item to be updated towards the plugin
        :param caller: if given it represents the callers name
        :param source: if given it represents the source
        :param dest: if given it represents the dest
        '''
        # check if the item was changed by some other caller than this class
        # if so, send the values
        if self.has_iattr(item.conf, 'denon_avr_attribute') and caller != 'DenonAVR':
            self.logger.debug("update_item_callback was called with item '{}' from caller '{}', source '{}' and dest '{}'".format(item, caller, source, dest))
            denon_attrib = self.get_iattr_value(item.conf, 'denon_avr_attribute')
            self.recv_lock.acquire()
            success = self.send_command(cmd=denon_attrib,
                                        value=item())
            # if the command is power = on, we need to wait for a second before
            # we can make any other calls. All other commands return an answer
            # within 200ms according to the documentation.
            if denon_attrib == 'power' and item():
                time.sleep(1.0)
            else:
                time.sleep(0.2)
            # try to receive the ACK response
            try:
                denon_response = self.sock.recv(2048).decode()
                resp_dict = self._parse_response(denon_response)
                # check if the command did really come through
                if denon_attrib not in resp_dict:
                    # the reponse did not ACK the command, raise BlockingIOError just to trigger the
                    # no success mode
                    raise BlockingIOError
                # check if the correct value is returned
                if resp_dict[denon_attrib] != item():
                    raise BlockingIOError
                # the command was ACK'ed, everything is perfect
                # the dict may, however, contain other messages which we have to process
                # first, delete the rseponse to the current command then process all others
                del resp_dict[denon_attrib]
                self._update_items_from_response_dict(resp_dict) 
            except BlockingIOError:
                success = False
            if not success:
                self.logger.error('Unable to set DenonAVR attribute %s to %s', denon_attrib, str(item()))
                # reset item to previous value
                item(value=item.prev_value(), caller='DenonAVR')
            self.recv_lock.release()
                
    def _parse_response(self, denon_response):
        '''
        Parse the given response. Commands known from the internal
        command dictionary are parsed into a response dictionary and returned.
        For special commands, this method handles everything internally such as
        setting the allowed max volume for the AVR
        
        :param denon_response: (str) The response received from the AVR
        '''
        denon_response = denon_response.split('\r')
        denon_response = [elem for elem in denon_response if elem != '']
        self.logger.debug('Received %s', ', '.join(denon_response))
        # first two characters are command, rest is value
        response_dict = dict()
        for elem in denon_response:
            # some responses from the dict need to be handled
            if elem.startswith('MVMAX'):
                max_volume = elem.split(' ')[-1]
                max_volume = mv_from_avr(max_volume)
                self.logger.debug('Found new maximum master volume: %f', max_volume)
                self.max_volume = max_volume
            else:
                # do the general handling
                cmd = elem[:2]
                value = elem[2:]
                if cmd in self._inv_cmd_dict:
                    # translate only the known commands, ignore others
                    cmd = self._inv_cmd_dict[cmd]
                    value = self._cmd_dict[cmd]['from_avr'](value)
                    response_dict[cmd] = value
        return response_dict        
    
    def _recv_loop(self, recv_sleep):
        """
        this method shall only be used by the internal thread responsible for receiving
        responses by the receiver
        """
        while self.alive:
            time.sleep(recv_sleep)
            try:
                self.recv_lock.acquire()
                denon_response = self.sock.recv(2048).decode()
                response_dict = self._parse_reponse(denon_response)
                self._update_items_from_response_dict(response_dict)
            except BlockingIOError:
                # the recv command has timed out
                pass
            finally:
                self.recv_lock.release()
    
    def _update_items_from_response_dict(self, response_dict):
        '''
        Update all the items this Plugin is registered to
        according to the reponse dict received from the AVR device
        '''
        for cmd, value in response_dict.items():
            if cmd in self.item_dicts:
                for item in self.item_dicts[cmd]:
                    item(value=value, caller='DenonAVR')        

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(relativeCreated)6d %(threadName)s %(message)s')
    avr = DenonAVR(sh='smarthome-dummy', host='192.168.0.28')
    avr.run()
    avr.request_info('power')
    avr.stop()

