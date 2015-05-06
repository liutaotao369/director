import os
import vtkAll as vtk
from ddapp import botpy
import math
import numpy as np

from ddapp import transformUtils
from ddapp import lcmUtils
from ddapp.timercallback import TimerCallback
from ddapp import objectmodel as om
from ddapp import visualization as vis
from ddapp import applogic as app
from ddapp.debugVis import DebugData
from ddapp import ioUtils
from ddapp.simpletimer import SimpleTimer
from ddapp.utime import getUtime
import time

import drc as lcmdrc
from mav.indexed_measurement_t import indexed_measurement_t


class SystemStatusListener(object):

    def __init__(self, outputConsole):
        self.outputConsole = outputConsole
        lcmUtils.addSubscriber('SYSTEM_STATUS', lcmdrc.system_status_t, self.onSystemStatus)

    def onSystemStatus(self, message):
        message = 'SYSTEM_STATUS: ' + message.value
        if self.outputConsole is not None:
            self.outputConsole.append(message)
        else:
            print message


class AtlasDriver(object):

    def __init__(self):

        self.lastAtlasStatusMessage = None
        self.lastControllerStatusMessage = None
        self.lastAtlasBatteryDataMessage = None
        self.lastAtlasElectricArmStatusMessage = None
        self._setupSubscriptions()
        self.timer = SimpleTimer()

        self.sentStandUtime = None
        self.startupStage = 0
        self._behaviorMap = None
        self._controllerStatusMap = None

    def _setupSubscriptions(self):
        lcmUtils.addSubscriber('CONTROLLER_STATUS', lcmdrc.controller_status_t, self.onControllerStatus)
        lcmUtils.addSubscriber('ATLAS_BATTERY_DATA', lcmdrc.atlas_battery_data_t, self.onAtlasBatteryData)
        lcmUtils.addSubscriber('ATLAS_ELECTRIC_ARM_STATUS', lcmdrc.atlas_electric_arm_status_t, self.onAtlasElectricArmStatus)
        sub = lcmUtils.addSubscriber('ATLAS_STATUS', lcmdrc.atlas_status_t, self.onAtlasStatus)
        sub.setSpeedLimit(60)

    def onAtlasStatus(self, message):
        self.lastAtlasStatusMessage = message

    def onControllerStatus(self, message):
        self.lastControllerStatusMessage = message

    def onAtlasBatteryData(self, message):
        self.lastAtlasBatteryDataMessage = message

    def onAtlasElectricArmStatus(self, message):
        self.lastAtlasElectricArmStatusMessage = message

    def getBehaviorMap(self):
        '''
        Return a dict that maps behavior ids (int) to behavior names (string).
        '''
        if not self._behaviorMap:
            msg = lcmdrc.atlas_status_t
            self._behaviorMap = {
                    msg.BEHAVIOR_NONE        : 'none',
                    msg.BEHAVIOR_FREEZE      : 'freeze',
                    msg.BEHAVIOR_STAND_PREP  : 'prep',
                    msg.BEHAVIOR_STAND       : 'stand',
                    msg.BEHAVIOR_WALK        : 'walk',
                    msg.BEHAVIOR_STEP        : 'step',
                    msg.BEHAVIOR_MANIPULATE  : 'manip',
                    msg.BEHAVIOR_USER        : 'user',
                    msg.BEHAVIOR_CALIBRATE   : 'calibrate',
                    msg.BEHAVIOR_SOFT_STOP   : 'stop',
                    }
        return self._behaviorMap

    def getControllerStatusMap(self):
        '''
        Return a dict that maps controller status ids (int) to names (string).
        '''
        if not self._controllerStatusMap:
            msg = lcmdrc.controller_status_t
            self._controllerStatusMap = {
                    msg.UNKNOWN       : 'unknown',
                    msg.STANDING      : 'standing',
                    msg.WALKING       : 'walking',
                    msg.HARNESSED     : 'harnessed',
                    msg.QUASISTATIC   : 'quasistatic',
                    msg.BRACING       : 'bracing',
                    msg.CRAWLING      : 'crawling',
                    msg.DUMMY         : 'dummy',
                    msg.MANIPULATING  : 'manipulating',
                    msg.RECOVERING    : 'recovering',
                    }
        return self._controllerStatusMap

    def getCurrentBehaviorName(self):
        '''
        Returns the current behavior name as a string.  Returns None if the
        current behavior is unknown.  The current behavior is unknown if no
        atlas status messages have arrived since this class was initialized.
        The returned string is one of the behavior names in the values of
        the behavior map returned by getBehaviorMap().
        '''
        if not self.lastAtlasStatusMessage:
            return None

        behaviors = self.getBehaviorMap()
        behaviorId = self.lastAtlasStatusMessage.behavior
        assert behaviorId in behaviors
        return behaviors[behaviorId]

    def getControllerStatus(self):
        '''
        Returns the current controller status as a string.  The possible string
        values are the values of the dict returned by getControllerStatusMap().
        None is returned if no controller status message has been received or
        the status is not among those handled by this driver.
        '''
        if not self.lastControllerStatusMessage:
            return None

        statusMap = self.getControllerStatusMap()
        state = self.lastControllerStatusMessage.state
        assert state in statusMap
        return statusMap[state]

    def getRecoveryEnabledStatus(self):
        if not self.lastControllerStatusMessage:
            return None
        if self.lastControllerStatusMessage.recovery_enabled:
            return "enabled"
        else:
            return "disabled"

    def getElectricArmEnabledStatus(self, i):
        assert 0 <= i <= 5
        if self.lastAtlasElectricArmStatusMessage:
            return self.lastAtlasElectricArmStatusMessage.enabled[i]
        return False

    def getElectricArmTemperature(self, i):
        assert 0 <= i <= 5
        if self.lastAtlasElectricArmStatusMessage:
            return self.lastAtlasElectricArmStatusMessage.temperature[i]
        return 0.0

    def getElectricArmDriveCurrent(self, i):
        assert 0 <= i <= 5
        if self.lastAtlasElectricArmStatusMessage:
            return self.lastAtlasElectricArmStatusMessage.drive_current[i]
        return 0.0

    def getCurrentInletPressure(self):
        if self.lastAtlasStatusMessage:
            return self.lastAtlasStatusMessage.pump_inlet_pressure
        return 0.0

    def getCurrentSupplyPressure(self):
        if self.lastAtlasStatusMessage:
            return self.lastAtlasStatusMessage.pump_supply_pressure
        return 0.0

    def getCurrentReturnPressure(self):
        if self.lastAtlasStatusMessage:
            return self.lastAtlasStatusMessage.pump_return_pressure
        return 0.0

    def getCurrentAirSumpPressure(self):
        if self.lastAtlasStatusMessage:
            return self.lastAtlasStatusMessage.air_sump_pressure
        return 0.0

    def getCurrentPumpRpm(self):
        if self.lastAtlasStatusMessage:
            return self.lastAtlasStatusMessage.current_pump_rpm
        return 0.0

    def sendBehaviorCommand(self, behaviorName):

        msg = lcmdrc.atlas_behavior_command_t()
        msg.utime = getUtime()
        msg.command = behaviorName
        lcmUtils.publish('ATLAS_BEHAVIOR_COMMAND', msg)

    def sendStopCommand(self):
        self.sendBehaviorCommand('stop')

    def sendFreezeCommand(self):
        self.sendBehaviorCommand('freeze')

    def sendPrepCommand(self):
        self.sendBehaviorCommand('prep')

    def sendStandCommand(self):
        self.sendBehaviorCommand('stand')

    def sendCombinedStandCommand(self):
        self.sendBehaviorCommand('stand')
        self.startupStage = 1
        self.sentStandUtime = getUtime()

    def sendMITStandCommand(self):
        msg = lcmdrc.utime_t()
        msg.utime = getUtime()
        lcmUtils.publish('START_MIT_STAND', msg)

    def sendRecoveryEnable(self):
        msg = lcmdrc.boolean_t()
        msg.data = True
        lcmUtils.publish('RECOVERY_ENABLE', msg)

    def sendRecoveryDisable(self):
        msg = lcmdrc.boolean_t()
        msg.data = False
        lcmUtils.publish('RECOVERY_ENABLE', msg)

    def sendRecoveryTriggerOn(self):
        msg = lcmdrc.boolean_t()
        msg.data = True
        lcmUtils.publish('RECOVERY_TRIGGER', msg)

    def sendRecoveryTriggerOff(self):
        msg = lcmdrc.boolean_t()
        msg.data = False
        lcmUtils.publish('RECOVERY_TRIGGER', msg)

    def sendManipCommand(self):
        self.sendBehaviorCommand('manip')

    def sendUserCommand(self):
        self.sendBehaviorCommand('user')

    def sendCalibrateNullBiasCommand(self):
        self.sendBehaviorCommand('calibrate_null_bias')

    def sendCalibrateElectricArmsCommand(self):
        self.sendBehaviorCommand('calibrate_electric_arms')

    def sendElectricArmEnabledState(self, enabledState):
        msg = lcmdrc.atlas_electric_arm_enable_t()
        msg.utime = getUtime()
        msg.num_electric_arm_joints = 6
        assert len(enabledState) == msg.num_electric_arm_joints
        msg.enable = enabledState
        lcmUtils.publish('ATLAS_ELECTRIC_ARM_ENABLE', msg)

    def sendCalibrateEncodersCommand(self):
        msg = lcmdrc.utime_t()
        msg.utime = getUtime()
        lcmUtils.publish('CALIBRATE_ARM_ENCODERS', msg)

    def sendPlanUsingBdiHeight(self, enabled):
        msg = lcmdrc.plan_adjust_mode_t()
        msg.utime = getUtime()
        msg.mode = 1 if enabled else 0
        lcmUtils.publish('PLAN_USING_BDI_HEIGHT', msg)

    # State Est Init Code
    def sendInitAtZero(self):
        self.sendReadyMessage()
        p1 = [0,0,0.85]
        self.sendInitMessage(p1, 0)

    def sendReadyMessage(self):
        ready_init = lcmdrc.utime_t()
        ready_init.utime = getUtime()
        lcmUtils.publish('STATE_EST_READY', ready_init)
        time.sleep(1) # sleep needed to give SE time to restart


    def sendInitMessage(self, pos, yaw):
        init = indexed_measurement_t()
        init.utime = getUtime()
        init.state_utime = init.utime
        init.measured_dim = 4
        init.z_effective = [ pos[0], pos[1], pos[2] , yaw ]
        init.z_indices = [9, 10, 11, 8]

        init.measured_cov_dim = init.measured_dim*init.measured_dim
        init.R_effective= [0] * init.measured_cov_dim
        init.R_effective[0]  = 0.25
        init.R_effective[5]  = 0.25
        init.R_effective[10] = 0.25
        init.R_effective[15] =  math.pow( 50*math.pi/180 , 2 )

        lcmUtils.publish('MAV_STATE_EST_VIEWER_MEASUREMENT', init)


    def updateCombinedStandLogic(self):
        if (self.sentStandUtime is not None):
            if (self.startupStage == 1):
              if ( getUtime() > self.sentStandUtime + 6E6 ):
                  # print "Sending SE Init"
                  self.sendInitAtZero()
                  self.startupStage = 2

            elif (self.startupStage == 2):
              if ( getUtime() > self.sentStandUtime + 10E6 ):
                  self.sendBehaviorCommand('user')
                  self.sendMITStandCommand()
                  # print "Sending BDI User & MIT Stand commands"
                  self.startupStage = 0


    def getPelvisHeightLimits(self):
        '''
        returns pelvis height limits in meters: min, max
        '''
        return (0.66, 0.92)


    def sendPelvisHeightCommand(self, height):

        heightLimit = self.getPelvisHeightLimits()
        assert heightLimit[0] <= height <= heightLimit[1]

        pelvisParams = lcmdrc.atlas_behavior_pelvis_servo_params_t()
        pelvisParams.com_v0 = 0.0
        pelvisParams.com_v1 = 0.0
        pelvisParams.pelvis_height = height
        pelvisParams.pelvis_yaw = 0.0
        pelvisParams.pelvis_pitch = 0.0
        pelvisParams.pelvis_roll = 0.0

        msg = lcmdrc.atlas_behavior_manipulate_params_t()
        msg.use_demo_mode = 0
        msg.use_desired = 1
        msg.desired = pelvisParams

        lcmUtils.publish('ATLAS_MANIPULATE_PARAMS', msg)



def init(outputConsole=None):

    global driver
    driver = AtlasDriver()

    global systemStatus
    systemStatus = SystemStatusListener(outputConsole)

    return driver

