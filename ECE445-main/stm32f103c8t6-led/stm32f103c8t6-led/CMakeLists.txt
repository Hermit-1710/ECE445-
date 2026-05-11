cmake_minimum_required(VERSION 3.22)

#
# This file is generated only once,
# and is not re-generated if converter is called multiple times.
#
# User is free to modify the file as much as necessary
#

# Setup compiler settings
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)


# Define the build type
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE "Debug")
endif()

# Set the project name
set(CMAKE_PROJECT_NAME stm32f103c8t6-led)
set(DW_APP_ROLE "0" CACHE STRING "BU01 role: 0=selftest, 1=SS-TWR initiator tag, 2=SS-TWR responder anchor")
set(ANCHOR_ID "0" CACHE STRING "BU01 anchor id used by gateway/anchor roles: 0=A0, 1=A1, 2=A2, 3=A3")

# Include toolchain file
include("cmake/gcc-arm-none-eabi.cmake")

# Enable compile command to ease indexing with e.g. clangd
set(CMAKE_EXPORT_COMPILE_COMMANDS TRUE)

# Core project settings
project(${CMAKE_PROJECT_NAME})
message("Build type: " ${CMAKE_BUILD_TYPE})

# Enable CMake support for ASM and C languages
enable_language(C ASM)

# Create an executable object type
add_executable(${CMAKE_PROJECT_NAME})

# Add STM32CubeMX generated sources
add_subdirectory(cmake/stm32cubemx)

# Link directories setup
target_link_directories(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user defined library search paths
)

# Add sources to executable
target_sources(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user sources here
)

# Add include paths
target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user defined include paths
)

# Add project symbols (macros)
target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user defined symbols
    DW_APP_ROLE=${DW_APP_ROLE}
    ANCHOR_ID=${ANCHOR_ID}
)

# Add linked libraries
target_link_libraries(${CMAKE_PROJECT_NAME}
    stm32cubemx

    # Add user defined libraries
)

if(CMAKE_OBJCOPY)
    add_custom_command(TARGET ${CMAKE_PROJECT_NAME} POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E chdir $<TARGET_FILE_DIR:${CMAKE_PROJECT_NAME}>
                ${CMAKE_OBJCOPY} -O ihex $<TARGET_FILE_NAME:${CMAKE_PROJECT_NAME}> ${CMAKE_PROJECT_NAME}.hex
        COMMAND ${CMAKE_COMMAND} -E chdir $<TARGET_FILE_DIR:${CMAKE_PROJECT_NAME}>
                ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE_NAME:${CMAKE_PROJECT_NAME}> ${CMAKE_PROJECT_NAME}.bin
        COMMENT "Generating HEX and BIN artifacts"
    )

    set_target_properties(${CMAKE_PROJECT_NAME} PROPERTIES
        ADDITIONAL_CLEAN_FILES "${CMAKE_PROJECT_NAME}.hex;${CMAKE_PROJECT_NAME}.bin"
    )
endif()
