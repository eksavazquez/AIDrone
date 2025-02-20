#!/usr/bin/env python3

import asyncio
from mavsdk import System
from mavsdk.geofence import Point
from mavsdk.action import OrbitYawBehavior
import datetime
import numpy as np
import os
import json

PORT = 14540
NUMDRONES = 1
STATUS = ['F','M','A2','A3','A4','A5','PC2', 'PC3', 'PC4', 'PC5'] 
EPSILON = 0.9
DISCOUNT_FACTOR = 0.9
LEARNING_RATE = 0.9

async def run():
    
    latitude = 0
    longitude = 0
    absolute_altitude = 0
    flying_alt = 80
    is_flying = False
    record = []


    PC = Point(latitude, longitude)
    A = Point(latitude + 0.001, longitude - 0.001)
    POINTS = {}
    q_values = {}
    
    # Si existe el json con el qvalue lo carga
    if(not os.path.exists("JSON")):
        os.mkdir("JSON")
    if os.path.isfile("JSON/q_values.json"):
        with open("JSON/q_values.json") as json_file:
            q_values = json.load(json_file)
    else:
        q_values= {'F':[0,0],'M':[0,0],'A2':[0,0],'A3':[0,0],'A4':[0,0],'A5':[0,0],'PC2':[0,0], 'PC3':[0,0], 'PC4':[0,0], 'PC5':[0,0]}
    rewards = {'F':0,'M':-5000,'A2':20,'A3':20,'A4':20,'A5':20,'PC2':0, 'PC3':0, 'PC4':0, 'PC5':0}

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
            
            
    async def AIDrone(idDrone, episode):

        async def go_to(idDrone):

            last_point = record[idDrone][-1]
            if(last_point=="PC"): #Si está en un punto, va hacia el otro punto 
                point= POINTS["A"]
            else:
                point= POINTS["PC"]
            global is_flying
            if not is_flying:
                print("-- Arming")
                await drone.action.arm()
                print("-- Taking off")
                await drone.action.takeoff()
                
            await drone.action.goto_location(point.latitude_deg, point.longitude_deg, flying_alt, 0)
            is_flying=True

            battery = round(await get_battery(drone)*100,2)    
            name_point = [k for k, v in POINTS.items() if v == point][0]
            print("Going to " + name_point + " with " + str(battery) + " percentage at " + str(datetime.datetime.now().strftime('%H:%M:%S')) + " (" + await get_status() + ")")
            
            async for position in drone.telemetry.position():
                #Comprueba que llega al punto    
                if abs(position.latitude_deg-point.latitude_deg)<0.00001 and abs(position.longitude_deg-point.longitude_deg)<0.00001: 
                    record[idDrone].append(name_point) # Guarda en el historial en que punto está
                    break
        
        async def act(idDrone):
            actual_point = record[idDrone][-1]
            battery = round(await get_battery(drone)*100,2)
            actual_status = await get_status()    
            global is_flying

            if(actual_point == "PC"):
                if is_flying:      #Se optimiza para que cargue más rapido cuando esté en el suelo
                    print("Acting on point " + actual_point + " with " + str(battery) + " percentage at " + str(datetime.datetime.now().strftime('%H:%M:%S')) + " (" + actual_status + ")")
                    await drone.action.land()

                    i=0
                    async for in_air_local in drone.telemetry.in_air():
                        if(i%20==0):
                            print("Trying to land, still in air. Still " + str(round(await get_altitude(drone),2)) + " from ground.")
                        i = i+1
                        if not in_air_local:
                            is_flying=False
                            break
                print("Charging battery at " + actual_point + " with " + str(round(await get_battery(drone)*100,2)) + " percentage at " + str(datetime.datetime.now().strftime('%H:%M:%S')) + " (" + await get_status() + ")")

            else:
                print("Monitoring point " + actual_point + " with " + str(battery) + " percentage at " + str(datetime.datetime.now().strftime('%H:%M:%S')) + " (" + actual_status + ")")
                await drone.action.do_orbit(radius_m=2.0, velocity_ms=10.0, yaw_behavior = OrbitYawBehavior.HOLD_FRONT_TO_CIRCLE_CENTER, latitude_deg = POINTS[actual_point].latitude_deg, longitude_deg = POINTS[actual_point].longitude_deg, absolute_altitude_m = absolute_altitude + 20)
                await asyncio.sleep(10)

            record[idDrone].append(actual_point)
            
        async def get_battery_status(drone):
            battery= await get_battery(drone)
            #TODO Ver como funcionan estos valores 
            battery_levels = {1 : 0.16, 2: 0.45, 3: 0.60, 4: 0.8, 5: 1.0}
            
            battery_status = [k for k, v in battery_levels.items() if v >= battery][0]
            return battery_status

        async def get_status():
        #['F','M','A2','A3','A4','A5','PC2', 'PC3', 'PC4', 'PC5'] 

            battery_status = await get_battery_status(drone)
            point = record[idDrone][-1]
            global is_flying

            if(battery_status==1):
                if(point=="M"):
                    return "F"
                if is_flying:
                    record[idDrone].append("M")
                    print("Mayday! Mayday! Drone without battery " + "(M)")

                    return "M"
            
            status = point+str(battery_status)
            return status

        def get_next_action(state, epsilon):
            #if a randomly chosen value between 0 and 1 is less than epsilon, 
            #then choose the most promising value from the Q-table for this state.
            
            if np.random.random() < epsilon:
                return np.argmax(q_values[state])
            else: #choose a random action
                return np.random.randint(2)
        
        async def get_next_status(action_index):
            action=actions_functions[action_index]
            await action(idDrone)
            return await get_status()

        async def reset_episode(drone, episode):
            await drone.action.goto_location(POINTS["PC"].latitude_deg, POINTS["PC"].longitude_deg, flying_alt, 0)
            async for position in drone.telemetry.position():
                #Comprueba que llega al punto    
                if abs(position.latitude_deg-POINTS["PC"].latitude_deg)<0.00001 and abs(position.longitude_deg-POINTS["PC"].longitude_deg)<0.00001: 
                    break
            
            # Aterriza y carga la batería
            global is_flying
            if is_flying:      
                    await drone.action.land()
                    async for in_air_local in drone.telemetry.in_air():
                        if not in_air_local:
                            is_flying=False
                            break
                        
            await asyncio.sleep(4)
            print("Starting new episode - Episode " + str(episode+1))

        actions_functions = [act,go_to]
        global is_flying
        is_flying = True

        status = await get_status()

        while(status != "M"):
            status = await get_status()

            action_index=get_next_action(status, EPSILON)

            #perform the chosen action, and transition to the next state (i.e., move to the next location)
            old_status = status #store the old row and column indexes

            status = await get_next_status(action_index)

            #receive the reward for moving to the new state, and calculate the temporal difference
            reward = rewards[status]
            old_q_value = q_values[old_status][action_index]
            temporal_difference = reward + (DISCOUNT_FACTOR * np.max(q_values[status])) - old_q_value
            
            new_q_value = old_q_value + (LEARNING_RATE * temporal_difference)
            q_values[old_status][action_index] = new_q_value #actualización
            with open("JSON/q_values.json", 'w') as outfile:
                json.dump(q_values, outfile) #actualizacion en json

        await reset_episode(drone, episode)

        
    ### Código a ejecutar en run() ###

    print("Drone 0")
    drone = System()
    await drone.connect(system_address="udp://:"+str(PORT))

    status_text_task = asyncio.ensure_future(print_status_text(drone))

    print("Waiting for drone to have a global position estimate...")
    async for health in drone.telemetry.health():
        if health.is_global_position_ok and health.is_home_position_ok:
            print("-- Global position estimate OK")
            break

    print("Fetching home location coordinates and altitude...")
    async for terrain_info in drone.telemetry.home():
        latitude = terrain_info.latitude_deg
        longitude = terrain_info.longitude_deg
        absolute_altitude = terrain_info.absolute_altitude_m
        flying_alt = absolute_altitude + 40
        PC = Point(latitude, longitude)
        A = Point(latitude + 0.001, longitude - 0.001)
        POINTS= {
            "PC": PC,
            "A": A
        }
        break
    record.append([])
    for episode in range(100):
        record[0].append("PC")
        print("-- Arming")
        await drone.action.arm()
        
        print("-- Taking off")
        await drone.action.takeoff()
        await AIDrone(0,episode)

    print("Training completed")
    print(q_values)


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
    loop.run_until_complete(run())