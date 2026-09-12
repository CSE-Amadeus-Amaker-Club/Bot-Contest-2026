# READ THIS FIRST!
We strongly recommend to read this document before jumping in contest :)

#  Introduction

This document is your practical guide for the aMaker contest.
It covers the essential steps to build a functional bot using the elements and win the contest.

# Bill of material
You should have received: 
* 1 microcontroller board (with screen and camera)
* 1 extension board, with a battery holder, lots of pins, **power switch** and **USB connector** for battery charging.
* 1 battery 18650 (loaded). **Be extremely carefull with polarity when plugin the battery**
* 1 set of lego bricks with plates, wheels, axles, tracks, gears. ![Bill%20of%20material%20pieces.jpg](Bill%20of%20material%20pieces.jpg) ~[book_chapters.png](book_chapters.png)
* 2 servo motors : green ones 
![svgreen64.png](svgreen64.png)
* 2 angular servos : grey  ones ![svgrey64.png](svgrey64.png)
* 1 toothpicks
* 1 balloon


# Contest objective
Build the best remote controlled bot, a champion that will keep its balloon longer than others. 


# Participant guide
You'll have to design and assemble your own bot with the provided pieces.

Electronics is very easy you just have to 
- plug the microcontroller board in the extension board
- plug the servos you want to use to extension board pins S0 to S5 at your convenience.
- plug the i2c sensors and huskylens to **I2C 3.3V** 
- connect the LIDAR wires : green->p0 and blue->p1 (left side), red->5V black->GND (right side)
![wiring.png](wiring.png)
When powered ** NEVER EVER LOOK AT LIDAR IN FRONT OF CAMERA **: it emits **invisible 905nm laser beams** and has no class 1 certification. 


Controlling your bot will be done via your computer using autonomous code,  keyboard, mouse,  joystick... 


## Building your bot

### Contraints
1. The electronics parts have to be protected from toothpicks (using transparent sheet or lego pieces)
1. The camera field of view must be free of obstacle (~90 degrees)
1. The LIDAR field of view must be free of obstacle (~120 degrees horizontally)
1. The balloon will be inflated and mounted **by your oppenent** ;)


### Moving your bot
Most common way are here under:

#### Tank mode
One motor on left track, one right track. 
Motors running in same direction => going forward / backward.
Motors running in opposite direction => turning on itself.

#### Car mode
One motor on the differential in and two wheels on the differential out, angular servo controls two direction wheels. Like a car. 

#### ... 
There are plenty of other ways to nove your bot: be creative.


### Motor control
![svgreen64.png](svgreen64.png)

Motor speed can be set from -100 to +100. 
You may find some benefits using the gears to multiply rotation speed.

Mounting Motors may be tricky as holes are not symetrical on the box : some holes are 1/2 depth.


### Angle control
![svgrey64.png](svgrey64.png)

Angular servo be set from 0 to 270 degree.
 

### Mounting the toothpick
There are lots of ways to mount your tooth picks:
- static at end of a pole
- attached at end of and articulated arm
- ...

### Mounting your balloon
You balloon will be fairly mounted by your oppenent.


### Tips an tricks
- triple check the battery polarity before inserting and powering. 
- double check the servo connection direction
- Let the USB-c connector accessible
- Use the USB-c connector to charge the battery
- Let the power switch accessible
- Be iterative
- If you lack ideas, have a look at the book [The LEGO power functions idea book., Isogawa, Yoshihito](https://archive.org/details/legopowerfunctio0000isog_f2e0/page/4/mode/2up) : there are lots of ideas ![contest-guide-ideas.png](contest-guide-ideas.png).

## Coding part

### Contest firmware.
The microcontroller is provided with a custom firmware for the contest.

#### Setup WiFi (optional)
On first boot, if no known WiFi is accessible, board will open its own access point `amaker-XXXXX` and show its name on screen. Connect to it using password `amaker-club`.
Once connected, open page [http://192.168.4.1](http://192.168.4.1)

The home page allows to configure a "public" WiFi access point to use:
- set master token (it's present on screen), click register
- define WiFi SSID and password and save.
- reboot to start using this WiFi network.

#### Website (port 80)
The microcontroller exposes a website on port 80.
It exposes the WiFi setup page, camera view page, and build information page.

#### UDP (port 24642)
The microcontroller exposes a UDP service on port 24642.

### Coding your controller

#### Code your own client
You will code your own controller that interacts with the bot firmware via UDP
Protocol documentation is provided in markdown for your prefered LLM :)

#### Example code
A python client is present in repo.


