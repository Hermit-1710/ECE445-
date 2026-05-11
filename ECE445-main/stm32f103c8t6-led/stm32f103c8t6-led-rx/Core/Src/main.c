/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "spi.h"
#include "usart.h"
#include "gpio.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include "deca_device_api.h"
#include "deca_regs.h"
#include "port.h"
#include <stdio.h>
#include <string.h>

/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */
static dwt_config_t dw1000_test_config = {
  2,
  DWT_PRF_64M,
  DWT_PLEN_1024,
  DWT_PAC32,
  9,
  9,
  1,
  DWT_BR_110K,
  DWT_PHRMODE_STD,
  (1025 + 64 - 32)
};

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define FRAME_LEN_MAX 127U
#define RX_FRAME_LEN 12U
#define RX_FRAME_SRC_IDX 2U
#define DATA_FRAME_SN_IDX 2U
#define DATA_FRAME_DEST_IDX 5U

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/

/* USER CODE BEGIN PV */
static volatile uint32_t dw_irq_count = 0;
static uint32_t last_reported_dw_irq_count = 0;
static uint8_t dw1000_rx_ready = 0;
static uint8_t rx_buffer[FRAME_LEN_MAX];
static uint8_t resp_msg[] = {0x41, 0x8C, 0, 0x9A, 0x60, 0, 0, 0, 0, 0, 0, 0, 0, 'D', 'W', 0x10, 0x00, 0, 0, 0, 0};

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
/* USER CODE BEGIN PFP */
static void uart_log(const char *msg);
static void dw1000_irq_test_init(void);
static int dw1000_driver_init(void);
static void dw1000_configure_default(void);
static void dw1000_rx_loop(void);
static uint8_t dw1000_frame_is_expected(const uint8_t *frame, uint16_t frame_len);
static void dw1000_prepare_response(const uint8_t *frame);
static void uart_log_frame_hex(const char *prefix, const uint8_t *frame, uint16_t frame_len);

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */
static void uart_log(const char *msg)
{
  HAL_UART_Transmit(&huart1, (uint8_t *)msg, (uint16_t)strlen(msg), HAL_MAX_DELAY);
}

static void uart_log_frame_hex(const char *prefix, const uint8_t *frame, uint16_t frame_len)
{
  char buffer[16];
  uint16_t i;

  uart_log(prefix);
  for (i = 0; i < frame_len; i++)
  {
    snprintf(buffer, sizeof(buffer), "%02X%s", frame[i], (i + 1U < frame_len) ? " " : "\r\n");
    uart_log(buffer);
  }
}

static void dw1000_irq_test_init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  GPIO_InitStruct.Pin = DW_IRQ_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_IT_RISING;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(DW_IRQ_GPIO_Port, &GPIO_InitStruct);

  uart_log("[RX-BOARD] DW_IRQ configured for rising-edge EXTI\r\n");
}

static int dw1000_driver_init(void)
{
  char buffer[96];
  int init_status;
  uint32_t device_id;

  uart_log("[RX-BOARD] Resetting DW1000\r\n");
  reset_DW1000();

  uart_log("[RX-BOARD] Setting SPI to slow rate for init\r\n");
  port_set_dw1000_slowrate();

  init_status = dwt_initialise(DWT_LOADNONE);
  snprintf(buffer, sizeof(buffer), "[RX-BOARD] dwt_initialise() = %d\r\n", init_status);
  uart_log(buffer);

  if (init_status == DWT_ERROR)
  {
    uart_log("[RX-BOARD] DW1000 init failed\r\n");
    return DWT_ERROR;
  }

  port_set_dw1000_fastrate();
  device_id = dwt_readdevid();
  snprintf(buffer, sizeof(buffer), "[RX-BOARD] Device ID = 0x%08lX\r\n", device_id);
  uart_log(buffer);

  return DWT_SUCCESS;
}

static void dw1000_configure_default(void)
{
  char buffer[96];

  dwt_configure(&dw1000_test_config);
  snprintf(buffer, sizeof(buffer),
           "[RX-BOARD] Configured: ch=%u prf=%u plen=%u rate=%u\r\n",
           dw1000_test_config.chan,
           dw1000_test_config.prf,
           dw1000_test_config.txPreambLength,
           dw1000_test_config.dataRate);
  uart_log(buffer);
}

static uint8_t dw1000_frame_is_expected(const uint8_t *frame, uint16_t frame_len)
{
  (void)frame;
  return (uint8_t)(frame_len == RX_FRAME_LEN);
}

static void dw1000_prepare_response(const uint8_t *frame)
{
  uint32_t i;

  for (i = 0; i < 8U; i++)
  {
    resp_msg[DATA_FRAME_DEST_IDX + i] = frame[RX_FRAME_SRC_IDX + i];
  }
}

static void dw1000_rx_loop(void)
{
  uint32_t status_reg;
  uint16_t frame_len;
  char buffer[96];

  dwt_rxenable(DWT_START_RX_IMMEDIATE);

  while (!((status_reg = dwt_read32bitreg(SYS_STATUS_ID)) & (SYS_STATUS_RXFCG | SYS_STATUS_ALL_RX_ERR)))
  {
  }

  if (status_reg & SYS_STATUS_RXFCG)
  {
    memset(rx_buffer, 0, sizeof(rx_buffer));
    frame_len = (uint16_t)(dwt_read32bitreg(RX_FINFO_ID) & RX_FINFO_RXFL_MASK_1023);
    if (frame_len <= FRAME_LEN_MAX)
    {
      dwt_readrxdata(rx_buffer, frame_len, 0);
    }

    dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_RXFCG);

    if ((frame_len <= FRAME_LEN_MAX) && dw1000_frame_is_expected(rx_buffer, frame_len))
    {
      uart_log_frame_hex("[RX-BOARD] RX data: ", rx_buffer, frame_len);
      dw1000_prepare_response(rx_buffer);
      dwt_writetxdata(sizeof(resp_msg), resp_msg, 0);
      dwt_writetxfctrl(sizeof(resp_msg), 0, 0);

      if (dwt_starttx(DWT_START_TX_IMMEDIATE) == DWT_ERROR)
      {
        uart_log("[RX-BOARD] dwt_starttx() returned error\r\n");
        return;
      }

      while (!(dwt_read32bitreg(SYS_STATUS_ID) & SYS_STATUS_TXFRS))
      {
      }

      dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_TXFRS);
      resp_msg[DATA_FRAME_SN_IDX]++;

      snprintf(buffer, sizeof(buffer), "[RX-BOARD] RX ok, response sent, seq=%u\r\n", resp_msg[DATA_FRAME_SN_IDX]);
      uart_log(buffer);
    }
    else
    {
      snprintf(buffer, sizeof(buffer), "[RX-BOARD] RX ignored, len=%u\r\n", frame_len);
      uart_log(buffer);
      if (frame_len <= FRAME_LEN_MAX)
      {
        uart_log_frame_hex("[RX-BOARD] Ignored data: ", rx_buffer, frame_len);
      }
    }
  }
  else
  {
    dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_ALL_RX_ERR);
    uart_log("[RX-BOARD] RX error detected, status cleared\r\n");
  }
}

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_SPI1_Init();
  MX_USART1_UART_Init();
  /* USER CODE BEGIN 2 */
  HAL_NVIC_SetPriority(EXTI0_IRQn, 2, 0);
  HAL_NVIC_EnableIRQ(EXTI0_IRQn);

  HAL_GPIO_WritePin(LED1_GPIO_Port, LED1_Pin, GPIO_PIN_SET);
  HAL_GPIO_WritePin(LED2_GPIO_Port, LED2_Pin, GPIO_PIN_RESET);
  dw1000_irq_test_init();
  if (dw1000_driver_init() == DWT_SUCCESS)
  {
    dw1000_configure_default();
    dw1000_rx_ready = 1;
    uart_log("[RX-BOARD] Entering receive/respond loop\r\n");
  }
  else
  {
    uart_log("[RX-BOARD] Stopping due to init failure\r\n");
  }

  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
    if (dw_irq_count != last_reported_dw_irq_count)
    {
      char buffer[64];
      last_reported_dw_irq_count = dw_irq_count;
      snprintf(buffer, sizeof(buffer), "[RX-BOARD] IRQ count=%lu\r\n", last_reported_dw_irq_count);
      uart_log(buffer);

      HAL_GPIO_TogglePin(LED1_GPIO_Port, LED1_Pin);
      HAL_GPIO_TogglePin(LED2_GPIO_Port, LED2_Pin);
    }
    if (dw1000_rx_ready)
    {
      dw1000_rx_loop();
    }
    else
    {
      HAL_Delay(200);
    }
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI_DIV2;
  RCC_OscInitStruct.PLL.PLLMUL = RCC_PLL_MUL16;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_2) != HAL_OK)
  {
    Error_Handler();
  }
}

/* USER CODE BEGIN 4 */
void HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin)
{
  if (GPIO_Pin == DW_IRQ_Pin)
  {
    dw_irq_count++;
  }
}

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}

#ifdef  USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
