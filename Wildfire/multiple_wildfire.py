#!/usr/bin/env python3

import asyncio
from multiprocessing import Pool
import threading
from mavsdk import System
from mavsdk.geofence import Point
from mavsdk.action import OrbitYawBehavior
import datetime
import value_and_policy_iteration

PORT = 14540
NUMDRONES = 3
STATUS = ['F','M','A2','A3','A4','A5','PC2', 'PC3', 'PC4', 'PC5'] 
POLICY_METHOD = "value iteration"

class Wildfire:
    
    latitude = 0
    longitude = 0
    absolute_altitude = 0
    flying_alt = 80
    is_flying = False
    record = []

    PC = Point(latitude, longitude)
    A = Point(latitude + 0.001, longitude - 0.001)
    POINTS= {}
    
    async def land_all(status_text_task):
        for num in range(NUMDRONES):
            print("Drone "+str(num))
            drone = System()
            portDrone= num+PORT
            await drone.connect(system_address="udp://:"+str(portDrone))
            print("-- Landing")
            await drone.action.land()

            status_text_task.cancel()
            
    async def print_battery(drone):
        async for battery in drone.telemetry.battery():
            print(f"{battery.remaining_percent}")
            break
    
    async def get_battery(drone):
        async for battery in drone.telemetry.battery():
            return battery.remaining_percent

    async def print_gps_info(drone):
        async for gps_info in drone.telemetry.gps_info():
            print(f"GPS info: {gps_info}")
            break

    async def print_in_air(drone):
        async for in_air_local in drone.telemetry.in_air():
            print(f"In air: {in_air_local}")
            break

    async def print_position(drone):
        async for position in drone.telemetry.position():
            print(position)
            break
    
    async def get_altitude(drone):
        async for position in drone.telemetry.position():
            return position.relative_altitude_m
    
    async def AIDrone(idDrone, drone, POINTS):
        async def go_to(idDrone):

            last_point = Wildfire.record[idDrone][-1]
            
            if(last_point=="PC"): #Si está en un punto, va hacia el otro punto 
                point= Wildfire.POINTS["A"]
            else:
                point= Wildfire.POINTS["PC"]
            global is_flying
            if not is_flying:
                print("-- Arming")
                await drone.action.arm()
                print("-- Taking off")
                await drone.action.takeoff()
                
            await drone.action.goto_location(point.latitude_deg, point.longitude_deg, Wildfire.flying_alt + idDrone, 0)
            is_flying=True

            battery = round(await Wildfire.get_battery(drone)*100,2)    
            name_point = [k for k, v in POINTS.items() if v == point][0]
            print("Dron " + str(idDrone) + " going to " + name_point + " with " + str(battery) + " percentage at " + str(datetime.datetime.now().strftime('%H:%M:%S')) + " (" + await get_status() + ")")
            
            async for position in drone.telemetry.position():
                #Comprueba que llega al punto    
                if abs(position.latitude_deg-point.latitude_deg)<0.00001 and abs(position.longitude_deg-point.longitude_deg)<0.00001: 
                    Wildfire.record[idDrone].append(name_point) # Guarda en el historial en que punto está
                    break
        
        async def act(idDrone):
            actual_point = Wildfire.record[idDrone][-1]
            battery = round(await Wildfire.get_battery(drone)*100,2)
            actual_status = await get_status()    
            global is_flying

            if(actual_point == "PC"):
                if is_flying:      #Se optimiza para que cargue más rapido cuando esté en el suelo
                    print("Dron " + str(idDrone) + " acting on point " + actual_point + " with " + str(battery) + " percentage at " + str(datetime.datetime.now().strftime('%H:%M:%S')) + " (" + actual_status + ")")
                    await drone.action.land()

                    i=0
                    async for in_air_local in drone.telemetry.in_air():
                        if(i%20==0):
                            print("Dron " + str(idDrone) + " trying to land, still in air. Still " + str(round(await Wildfire.get_altitude(drone),2)) + " from ground.")
                        i = i+1
                        if not in_air_local:
                            is_flying=False
                            break
                print("Dron " + str(idDrone) + " charging battery at " + actual_point + " with " + str(round(await Wildfire.get_battery(drone)*100,2)) + " percentage at " + str(datetime.datetime.now().strftime('%H:%M:%S')) + " (" + await get_status() + ")")


            elif(actual_point == "M"):
                print("Dron " + str(idDrone) + " Mayday! Mayday! Drone without battery " + "(" + actual_status + ")")

            else:
                print("Dron " + str(idDrone) + " monitoring point " + actual_point + " with " + str(battery) + " percentage at " + str(datetime.datetime.now().strftime('%H:%M:%S')) + " (" + actual_status + ")")
                print(Wildfire.absolute_altitude+idDrone*15+20)
                if(idDrone==0):
                    await drone.action.do_orbit(radius_m=2.0, velocity_ms=10.0, yaw_behavior = OrbitYawBehavior.HOLD_FRONT_TO_CIRCLE_CENTER, latitude_deg = Wildfire.POINTS[actual_point].latitude_deg, longitude_deg = Wildfire.POINTS[actual_point].longitude_deg, absolute_altitude_m = Wildfire.absolute_altitude+idDrone*15+20)
                await asyncio.sleep(10)

            Wildfire.record[idDrone].append(actual_point)
            
        async def get_battery_status(drone):
            battery= await Wildfire.get_battery(drone)
            battery_levels = {1 : 0.16, 2: 0.45, 3: 0.60, 4: 0.8, 5: 1.0}
            
            battery_status = [k for k, v in battery_levels.items() if v >= battery][0]
            return battery_status

        #['F','M','A2','A3','A4','A5','PC2', 'PC3', 'PC4', 'PC5'] 
        async def get_status():
            battery_status = await get_battery_status(drone)
            point = Wildfire.record[idDrone][-1]
            global is_flying

            if(battery_status==1):
                if(Wildfire.record[idDrone][-1]=="M"):
                    return "F"
                if is_flying:
                    Wildfire.record[idDrone].append("M")
                    return "M"
            
            status = point+str(battery_status)
            return status
            

        policy = value_and_policy_iteration.wildfire_one_charge_one_point(POLICY_METHOD)
        actions_functions = [act,go_to]
        actions = ["Actua", "Viaja"]
        global is_flying
        is_flying = True

        status = await get_status()
        while(status != "M"):
            status = await get_status()
            action=actions_functions[policy[STATUS.index(status)]]

            await action(idDrone)

    async def drone_control(idDrone):
        Wildfire.record.append(["PC"])
        print("Drone "+str(idDrone))
        portSys = 50050 + idDrone
        drone = System(mavsdk_server_address="127.0.0.1", port=portSys)
        
        await drone.connect()

        print("Waiting for drone to have a global position estimate...")
        async for health in drone.telemetry.health():
            if health.is_global_position_ok and health.is_home_position_ok:
                print("-- Global position estimate OK")
                break
        
        print("-- Arming")
        await drone.action.arm()
        
        print("-- Taking off")
        await drone.action.takeoff()

        await Wildfire.AIDrone(idDrone, drone, Wildfire.POINTS)

    async def calculate_coordinates():
        portSys = 50050 
        drone = System(mavsdk_server_address="127.0.0.1", port=portSys)
        
        await drone.connect()
        
        print("Fetching home location coordinates and altitude...")
        async for terrain_info in drone.telemetry.home():
            latitude = terrain_info.latitude_deg
            longitude = terrain_info.longitude_deg
            absolute_altitude = terrain_info.absolute_altitude_m
            Wildfire.flying_alt = absolute_altitude + 40
            PC = Point(latitude, longitude)
            A = Point(latitude + 0.001, longitude - 0.001)
            Wildfire.POINTS= {
                "PC": PC,
                "A": A
            }

            break

        drone.__del__()
        
    ### Código a ejecutar en run() ###

    #Paralelizamos el proceso drone_control           
    def run():
        loop = asyncio.get_event_loop()
        for i in range(NUMDRONES):
            asyncio.ensure_future(Wildfire.drone_control(i))
        loop.run_forever()

async def print_status_text(drone):
    try:
        async for status_text in drone.telemetry.status_text():
            print(f"Status: {status_text.type}: {status_text.text}")
    except asyncio.CancelledError:
        return

async def get_drones():
    list_drones = []
    for num in range(NUMDRONES):
        drone= System()
        portDrone= num+PORT
        await drone.connect(system_address="udp://:"+str(portDrone))
        list_drones.append(drone)
    return list_drones

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(Wildfire.calculate_coordinates())
    Wildfire.run()