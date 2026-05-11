#include "port.h"
#include "deca_device_api.h"
#include "spi.h"

app_t app = {0};
port_deca_isr_t port_deca_isr = NULL;

unsigned long portGetTickCnt(void)
{
    return HAL_GetTick();
}

void Sleep(uint32_t Delay)
{
    HAL_Delay(Delay);
}

int port_is_boot1_on(uint16_t x)
{
    UNUSED(x);
    return 0;
}

int port_is_switch_on(uint16_t GPIOpin)
{
    UNUSED(GPIOpin);
    return 0;
}

int port_is_boot1_low(void)
{
    return 0;
}

void port_wakeup_dw1000(void)
{
    HAL_GPIO_WritePin(DW_NSS_GPIO_Port, DW_NSS_Pin, GPIO_PIN_RESET);
    Sleep(1);
    HAL_GPIO_WritePin(DW_NSS_GPIO_Port, DW_NSS_Pin, GPIO_PIN_SET);
    Sleep(7);
}

void port_wakeup_dw1000_fast(void)
{
    port_wakeup_dw1000();
}

void port_set_dw1000_slowrate(void)
{
    hspi1.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_32;
    HAL_SPI_Init(&hspi1);
}

void port_set_dw1000_fastrate(void)
{
    hspi1.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_16;
    HAL_SPI_Init(&hspi1);
}

void process_dwRSTn_irq(void)
{
}

void process_deca_irq(void)
{
    if (port_deca_isr != NULL)
    {
        port_deca_isr();
    }
}

void led_on(led_t led)
{
    UNUSED(led);
}

void led_off(led_t led)
{
    UNUSED(led);
}

int peripherals_init(void)
{
    return 0;
}

void spi_peripheral_init(void)
{
}

void setup_DW1000RSTnIRQ(int enable)
{
    UNUSED(enable);
}

void reset_DW1000(void)
{
    HAL_GPIO_WritePin(DW_RST_GPIO_Port, DW_RST_Pin, GPIO_PIN_RESET);
    Sleep(2);
    HAL_GPIO_WritePin(DW_RST_GPIO_Port, DW_RST_Pin, GPIO_PIN_SET);
    Sleep(2);
}

void port_LCD_RS_set(void)
{
}

void port_LCD_RS_clear(void)
{
}

void port_LCD_RW_set(void)
{
}

void port_LCD_RW_clear(void)
{
}

ITStatus EXTI_GetITEnStatus(uint32_t x)
{
    return ((NVIC->ISER[(x >> 5UL)] & (uint32_t)(1UL << (x & 0x1FUL))) == (uint32_t)RESET) ? RESET : SET;
}

uint32_t port_GetEXT_IRQStatus(void)
{
    return EXTI_GetITEnStatus(EXTI0_IRQn);
}

uint32_t port_CheckEXT_IRQ(void)
{
    return HAL_GPIO_ReadPin(DW_IRQ_GPIO_Port, DW_IRQ_Pin);
}

void port_DisableEXT_IRQ(void)
{
    NVIC_DisableIRQ(EXTI0_IRQn);
}

void port_EnableEXT_IRQ(void)
{
    NVIC_EnableIRQ(EXTI0_IRQn);
}

HAL_StatusTypeDef flush_report_buff(void)
{
    return HAL_OK;
}
