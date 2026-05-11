/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : BU01/DW1000 phase 1 self-test and phase 2 SS-TWR demo.
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
#include <stdarg.h>
#include <string.h>
#include <math.h>
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */
typedef struct
{
  int16_t rx_power_cdbm;
  int16_t fp_power_cdbm;
  int16_t power_gap_cdb;
  uint16_t fp_index_q6;
  uint16_t rx_pream_count;
  uint16_t flags;
} range_diag_t;
/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/*
 * Compile-time role selector:
 *   DW_ROLE_SELFTEST          Phase 1: SPI/device-ID/IRQ/TX sanity test.
 *   DW_ROLE_INITIATOR_TAG     Phase 2: tag side, prints measured distance.
 *   DW_ROLE_RESPONDER_ANCHOR  Phase 2: anchor side, replies to tag polls.
 *   DW_ROLE_GATEWAY_A0        Phase 3: A0 gateway, replies to TAG and relays reports to PC.
 *   DW_ROLE_TAG_REPORTER      Phase 3: TAG, ranges with A0 and sends reports over UWB.
 */
#define DW_ROLE_SELFTEST 0
#define DW_ROLE_INITIATOR_TAG 1
#define DW_ROLE_RESPONDER_ANCHOR 2
#define DW_ROLE_GATEWAY_A0 3
#define DW_ROLE_TAG_REPORTER 4

#ifndef DW_APP_ROLE
#define DW_APP_ROLE DW_ROLE_SELFTEST
#endif

#ifndef ANCHOR_ID
#define ANCHOR_ID 0
#endif

#define DW_EXPECTED_DEV_ID 0xDECA0130UL
#define UART_LINE_MAX 320
#define SPEED_OF_LIGHT 299702547.0
#define UUS_TO_DWT_TIME 65536UL

#define TX_ANT_DLY 16436
#define RX_ANT_DLY 16436

#define ALL_MSG_COMMON_LEN 10
#define ALL_MSG_SN_IDX 2
#define POLL_MSG_TARGET_ID_IDX 10
#define RESP_MSG_POLL_RX_TS_IDX 10
#define RESP_MSG_RESP_TX_TS_IDX 14
#define RESP_MSG_TS_LEN 4
#define REPORT_MSG_CORR_CM_IDX 10
#define REPORT_MSG_RAW_CM_IDX 14
#define REPORT_MSG_STATUS_IDX 18
#define REPORT4_MSG_DIST0_IDX 10
#define REPORT4_MSG_DIST1_IDX 14
#define REPORT4_MSG_DIST2_IDX 18
#define REPORT4_MSG_DIST3_IDX 22
#define REPORT4_MSG_STATUS_IDX 26
#define REPORT4_MSG_DIAG_BASE_IDX 30
#define REPORT4_DIAG_STRIDE 12
#define REPORT4_MSG_LEN (REPORT4_MSG_DIAG_BASE_IDX + (4 * REPORT4_DIAG_STRIDE))
#define DIAG_RXPWR_CDBM_OFFSET 0
#define DIAG_FPPWR_CDBM_OFFSET 2
#define DIAG_GAP_CDB_OFFSET 4
#define DIAG_FP_INDEX_OFFSET 6
#define DIAG_RX_PACC_OFFSET 8
#define DIAG_FLAGS_OFFSET 10

#define RX_BUF_LEN 96
#define SELFTEST_PERIOD_MS 1000
#ifndef RNG_DELAY_MS
#define RNG_DELAY_MS 50
#endif
#ifndef INTER_ANCHOR_DELAY_MS
#define INTER_ANCHOR_DELAY_MS 0
#endif
#ifndef REPORT_TX_GUARD_MS
#define REPORT_TX_GUARD_MS 0
#endif
#ifndef POLL_TX_TO_RESP_RX_DLY_UUS
#define POLL_TX_TO_RESP_RX_DLY_UUS 180
#endif
#ifndef RESP_RX_TIMEOUT_UUS
#define RESP_RX_TIMEOUT_UUS 900
#endif
#ifndef POLL_RX_TO_RESP_TX_DLY_UUS
#define POLL_RX_TO_RESP_TX_DLY_UUS 650
#endif
#ifndef A0_VERBOSE_LOG
#define A0_VERBOSE_LOG 0
#endif

#define RANGE_BIAS_CM 0
/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */
/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/

/* USER CODE BEGIN PV */
static volatile uint32_t dw_irq_count = 0;

static dwt_config_t dw_config = {
  2,               /* Channel number. */
  DWT_PRF_64M,     /* Pulse repetition frequency. */
  DWT_PLEN_128,    /* Preamble length. */
  DWT_PAC8,        /* Preamble acquisition chunk size. */
  9,               /* TX preamble code. */
  9,               /* RX preamble code. */
  0,               /* Standard SFD. */
  DWT_BR_6M8,      /* Data rate. */
  DWT_PHRMODE_STD, /* PHY header mode. */
  (129 + 8 - 8)    /* SFD timeout. */
};

static uint8_t tx_poll_msg[] = {0x41, 0x88, 0, 0xCA, 0xDE, 'W', 'A', 'V', 'E', 0xE0, 0, 0, 0, 0};
static uint8_t rx_poll_msg[] = {0x41, 0x88, 0, 0xCA, 0xDE, 'W', 'A', 'V', 'E', 0xE0, 0, 0, 0, 0};
static uint8_t tx_resp_msg[] = {0x41, 0x88, 0, 0xCA, 0xDE, 'V', 'E', 'W', 'A', 0xE1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
static uint8_t rx_resp_msg[] = {0x41, 0x88, 0, 0xCA, 0xDE, 'V', 'E', 'W', 'A', 0xE1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
static uint8_t tx_report_msg[] = {0x41, 0x88, 0, 0xCA, 0xDE, 'A', '0', 'T', 'G', 0xE2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
static uint8_t rx_report_msg[] = {0x41, 0x88, 0, 0xCA, 0xDE, 'A', '0', 'T', 'G', 0xE2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
static uint8_t tx_report4_msg[REPORT4_MSG_LEN] = {0x41, 0x88, 0, 0xCA, 0xDE, 'A', '0', 'T', 'G', 0xE3};
static uint8_t rx_report4_msg[REPORT4_MSG_LEN] = {0x41, 0x88, 0, 0xCA, 0xDE, 'A', '0', 'T', 'G', 0xE3};
static uint8_t rx_buffer[RX_BUF_LEN];
static uint8_t frame_seq_nb = 0;
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
/* USER CODE BEGIN PFP */
static void uart_log(const char *msg);
static void uart_printf(const char *fmt, ...);
static void dw_irq_gpio_init(void);
static int dw1000_init_and_configure(void);
static int wait_for_status(uint32_t ok_mask, uint32_t err_mask, uint32_t timeout_ms, uint32_t *status_out);
static void app_selftest_loop(void);
static void app_initiator_loop(void);
static void app_responder_loop(void);
static void app_gateway_a0_loop(void);
static void app_tag_reporter_loop(void);
static uint64_t get_rx_timestamp_u64(void);
static void resp_msg_set_ts(uint8_t *ts_field, uint64_t ts);
static void resp_msg_get_ts(uint8_t *ts_field, uint32_t *ts);
static void msg_set_i16(uint8_t *field, int16_t value);
static int16_t msg_get_i16(const uint8_t *field);
static void msg_set_u16(uint8_t *field, uint16_t value);
static uint16_t msg_get_u16(const uint8_t *field);
static void msg_set_i32(uint8_t *field, int32_t value);
static int32_t msg_get_i32(const uint8_t *field);
static int twr_poll_anchor(uint8_t anchor_id, int32_t *corrected_cm, int32_t *raw_cm, uint32_t *range_status, range_diag_t *diag);
static range_diag_t read_range_diag(void);
static void report4_set_diag(uint8_t anchor_id, const range_diag_t *diag);
static range_diag_t report4_get_diag(uint8_t anchor_id);
/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */
static void uart_log(const char *msg)
{
  HAL_UART_Transmit(&huart1, (uint8_t *)msg, (uint16_t)strlen(msg), HAL_MAX_DELAY);
}

static void uart_printf(const char *fmt, ...)
{
  char buffer[UART_LINE_MAX];
  va_list args;

  va_start(args, fmt);
  vsnprintf(buffer, sizeof(buffer), fmt, args);
  va_end(args);
  uart_log(buffer);
}

static void dw_irq_gpio_init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  GPIO_InitStruct.Pin = DW_IRQ_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_IT_RISING;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(DW_IRQ_GPIO_Port, &GPIO_InitStruct);

  HAL_NVIC_SetPriority(EXTI0_IRQn, 2, 0);
  HAL_NVIC_EnableIRQ(EXTI0_IRQn);
}

static int dw1000_init_and_configure(void)
{
  uint32_t device_id;

  uart_log("\r\n[BU01] Boot\r\n");
  uart_log("[BU01] Reset DW1000\r\n");
  reset_DW1000();

  uart_log("[BU01] SPI slow init\r\n");
  port_set_dw1000_slowrate();
  if (dwt_initialise(DWT_LOADUCODE) == DWT_ERROR)
  {
    uart_log("[BU01] ERROR: dwt_initialise failed\r\n");
    return DWT_ERROR;
  }

  port_set_dw1000_fastrate();
  device_id = dwt_readdevid();
  uart_printf("[BU01] DEV_ID=0x%08lX\r\n", (unsigned long)device_id);

  if (device_id != DW_EXPECTED_DEV_ID)
  {
    uart_log("[BU01] ERROR: unexpected DEV_ID, check SPI/CS/RST wiring\r\n");
    return DWT_ERROR;
  }

  dwt_configure(&dw_config);
  dwt_setrxantennadelay(RX_ANT_DLY);
  dwt_settxantennadelay(TX_ANT_DLY);
  dwt_setinterrupt(DWT_INT_TFRS | DWT_INT_RFCG | DWT_INT_RFTO |
                   DWT_INT_RPHE | DWT_INT_RFCE | DWT_INT_RFSL |
                   DWT_INT_RXOVRR | DWT_INT_RXPTO | DWT_INT_SFDT,
                   1);

  uart_printf("[BU01] Config OK: ch=%u rate=%u preamble=%u\r\n",
              dw_config.chan,
              dw_config.dataRate,
              dw_config.txPreambLength);
  return DWT_SUCCESS;
}

static int wait_for_status(uint32_t ok_mask, uint32_t err_mask, uint32_t timeout_ms, uint32_t *status_out)
{
  uint32_t status;
  uint32_t start = HAL_GetTick();

  do
  {
    status = dwt_read32bitreg(SYS_STATUS_ID);
    if (status & ok_mask)
    {
      if (status_out != NULL)
      {
        *status_out = status;
      }
      return 1;
    }
    if (status & err_mask)
    {
      if (status_out != NULL)
      {
        *status_out = status;
      }
      return 0;
    }
  } while ((HAL_GetTick() - start) < timeout_ms);

  if (status_out != NULL)
  {
    *status_out = status;
  }
  return 0;
}

static void app_selftest_loop(void)
{
  static uint8_t tx_msg[] = {0xC5, 0, 'B', 'U', '0', '1', '-', 'T', 'E', 'S', 'T', 0, 0};
  uint32_t status = 0;
  uint32_t last_irq_count = 0;

  uart_log("[SELFTEST] Phase 1 active\r\n");
  uart_log("[SELFTEST] Expect: stable DEV_ID=0xDECA0130 and TX_OK every second\r\n");

  while (1)
  {
    tx_msg[1] = frame_seq_nb;

    dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_TXFRS | SYS_STATUS_RXFCG | SYS_STATUS_ALL_RX_ERR | SYS_STATUS_ALL_RX_TO);
    dwt_writetxdata(sizeof(tx_msg), tx_msg, 0);
    dwt_writetxfctrl(sizeof(tx_msg), 0, 0);

    if (dwt_starttx(DWT_START_TX_IMMEDIATE) == DWT_SUCCESS &&
        wait_for_status(SYS_STATUS_TXFRS, SYS_STATUS_ALL_RX_ERR, 100, &status))
    {
      dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_TXFRS);
      uart_printf("[SELFTEST] TX_OK seq=%u irq_total=%lu irq_delta=%lu status=0x%08lX\r\n",
                  frame_seq_nb,
                  (unsigned long)dw_irq_count,
                  (unsigned long)(dw_irq_count - last_irq_count),
                  (unsigned long)status);
      frame_seq_nb++;
      last_irq_count = dw_irq_count;
      HAL_GPIO_TogglePin(LED1_GPIO_Port, LED1_Pin);
    }
    else
    {
      uart_printf("[SELFTEST] TX_FAIL seq=%u status=0x%08lX\r\n",
                  frame_seq_nb,
                  (unsigned long)status);
      dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_TXFRS | SYS_STATUS_ALL_RX_ERR | SYS_STATUS_ALL_RX_TO);
      dwt_rxreset();
      HAL_GPIO_TogglePin(LED2_GPIO_Port, LED2_Pin);
    }

    uart_printf("[SELFTEST] DEV_ID=0x%08lX\r\n", (unsigned long)dwt_readdevid());
    HAL_Delay(SELFTEST_PERIOD_MS);
  }
}

static void app_initiator_loop(void)
{
  uint32_t status = 0;

  dwt_setrxaftertxdelay(POLL_TX_TO_RESP_RX_DLY_UUS);
  dwt_setrxtimeout(RESP_RX_TIMEOUT_UUS);

  uart_log("[TAG] Phase 2 SS-TWR initiator active\r\n");
  uart_log("[TAG] CSV: RANGE,seq,corrected_cm,raw_cm,status_hex\r\n");

  while (1)
  {
    tx_poll_msg[ALL_MSG_SN_IDX] = frame_seq_nb;
    tx_poll_msg[POLL_MSG_TARGET_ID_IDX] = 0;
    dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_TXFRS | SYS_STATUS_RXFCG | SYS_STATUS_ALL_RX_ERR | SYS_STATUS_ALL_RX_TO);
    dwt_writetxdata(sizeof(tx_poll_msg), tx_poll_msg, 0);
    dwt_writetxfctrl(sizeof(tx_poll_msg), 0, 1);

    if (dwt_starttx(DWT_START_TX_IMMEDIATE | DWT_RESPONSE_EXPECTED) != DWT_SUCCESS)
    {
      uart_printf("[TAG] START_TX_FAIL seq=%u\r\n", frame_seq_nb);
      HAL_Delay(RNG_DELAY_MS);
      continue;
    }

    if (wait_for_status(SYS_STATUS_RXFCG, SYS_STATUS_ALL_RX_TO | SYS_STATUS_ALL_RX_ERR, 20, &status))
    {
      uint32_t frame_len;

      dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_RXFCG);
      frame_len = dwt_read32bitreg(RX_FINFO_ID) & RX_FINFO_RXFL_MASK_1023;
      memset(rx_buffer, 0, sizeof(rx_buffer));
      if (frame_len <= RX_BUF_LEN)
      {
        dwt_readrxdata(rx_buffer, frame_len, 0);
      }

      rx_buffer[ALL_MSG_SN_IDX] = 0;
      if (memcmp(rx_buffer, rx_resp_msg, ALL_MSG_COMMON_LEN) == 0)
      {
        uint32_t poll_tx_ts;
        uint32_t resp_rx_ts;
        uint32_t poll_rx_ts;
        uint32_t resp_tx_ts;
        int32_t rtd_init;
        int32_t rtd_resp;
        double clock_offset_ratio;
        double tof;
        double distance_m;
        int32_t raw_distance_cm;
        int32_t corrected_distance_cm;

        poll_tx_ts = dwt_readtxtimestamplo32();
        resp_rx_ts = dwt_readrxtimestamplo32();
        clock_offset_ratio = dwt_readcarrierintegrator() *
                             (FREQ_OFFSET_MULTIPLIER * HERTZ_TO_PPM_MULTIPLIER_CHAN_2 / 1.0e6);

        resp_msg_get_ts(&rx_buffer[RESP_MSG_POLL_RX_TS_IDX], &poll_rx_ts);
        resp_msg_get_ts(&rx_buffer[RESP_MSG_RESP_TX_TS_IDX], &resp_tx_ts);

        rtd_init = (int32_t)(resp_rx_ts - poll_tx_ts);
        rtd_resp = (int32_t)(resp_tx_ts - poll_rx_ts);
        tof = ((rtd_init - rtd_resp * (1.0 - clock_offset_ratio)) / 2.0) * DWT_TIME_UNITS;
        distance_m = tof * SPEED_OF_LIGHT;
        raw_distance_cm = (int32_t)(distance_m * 100.0);
        corrected_distance_cm = raw_distance_cm + RANGE_BIAS_CM;

        uart_printf("RANGE,%u,%ld,%ld,0x%08lX\r\n",
                    frame_seq_nb,
                    (long)corrected_distance_cm,
                    (long)raw_distance_cm,
                    (unsigned long)status);
        HAL_GPIO_TogglePin(LED1_GPIO_Port, LED1_Pin);
      }
      else
      {
        uart_printf("[TAG] RX_UNEXPECTED seq=%u len=%lu status=0x%08lX\r\n",
                    frame_seq_nb,
                    (unsigned long)frame_len,
                    (unsigned long)status);
      }
    }
    else
    {
      uart_printf("[TAG] RX_TIMEOUT_OR_ERR seq=%u status=0x%08lX\r\n",
                  frame_seq_nb,
                  (unsigned long)status);
      dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_ALL_RX_TO | SYS_STATUS_ALL_RX_ERR);
      dwt_rxreset();
      HAL_GPIO_TogglePin(LED2_GPIO_Port, LED2_Pin);
    }

    frame_seq_nb++;
    HAL_Delay(RNG_DELAY_MS);
  }
}

static void app_responder_loop(void)
{
  uint32_t status = 0;
  uint32_t last_heartbeat = HAL_GetTick();

  uart_log("[ANCHOR] Phase 2 SS-TWR responder active\r\n");

  while (1)
  {
    if ((HAL_GetTick() - last_heartbeat) >= 500)
    {
      last_heartbeat = HAL_GetTick();
      HAL_GPIO_TogglePin(LED2_GPIO_Port, LED2_Pin);
    }

    dwt_rxenable(DWT_START_RX_IMMEDIATE);

    if (wait_for_status(SYS_STATUS_RXFCG, SYS_STATUS_ALL_RX_ERR, 1000, &status))
    {
      uint32_t frame_len;

      dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_RXFCG);
      frame_len = dwt_read32bitreg(RX_FINFO_ID) & RX_FINFO_RXFL_MASK_1023;
      memset(rx_buffer, 0, sizeof(rx_buffer));
      if (frame_len <= RX_BUF_LEN)
      {
        dwt_readrxdata(rx_buffer, frame_len, 0);
      }

      rx_buffer[ALL_MSG_SN_IDX] = 0;
      if (memcmp(rx_buffer, rx_poll_msg, ALL_MSG_COMMON_LEN) == 0 &&
          rx_buffer[POLL_MSG_TARGET_ID_IDX] == ANCHOR_ID)
      {
        uint64_t poll_rx_ts;
        uint64_t resp_tx_ts;
        uint32_t resp_tx_time;
        int ret;

        poll_rx_ts = get_rx_timestamp_u64();
        HAL_GPIO_TogglePin(LED2_GPIO_Port, LED2_Pin);
        resp_tx_time = (uint32_t)((poll_rx_ts + (POLL_RX_TO_RESP_TX_DLY_UUS * UUS_TO_DWT_TIME)) >> 8);
        dwt_setdelayedtrxtime(resp_tx_time);

        resp_tx_ts = (((uint64_t)(resp_tx_time & 0xFFFFFFFEUL)) << 8) + TX_ANT_DLY;
        resp_msg_set_ts(&tx_resp_msg[RESP_MSG_POLL_RX_TS_IDX], poll_rx_ts);
        resp_msg_set_ts(&tx_resp_msg[RESP_MSG_RESP_TX_TS_IDX], resp_tx_ts);

        tx_resp_msg[ALL_MSG_SN_IDX] = frame_seq_nb;
        dwt_writetxdata(sizeof(tx_resp_msg), tx_resp_msg, 0);
        dwt_writetxfctrl(sizeof(tx_resp_msg), 0, 1);
        ret = dwt_starttx(DWT_START_TX_DELAYED);

        if (ret == DWT_SUCCESS && wait_for_status(SYS_STATUS_TXFRS, SYS_STATUS_ALL_RX_ERR, 10, &status))
        {
          dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_TXFRS);
          uart_printf("[ANCHOR] RESP_OK seq=%u irq_total=%lu\r\n",
                      frame_seq_nb,
                      (unsigned long)dw_irq_count);
          frame_seq_nb++;
          HAL_GPIO_TogglePin(LED1_GPIO_Port, LED1_Pin);
        }
        else
        {
          uart_printf("[ANCHOR] RESP_TX_LATE_OR_FAIL ret=%d status=0x%08lX\r\n",
                      ret,
                      (unsigned long)status);
          dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_TXFRS | SYS_STATUS_ALL_RX_ERR);
        }
      }
    }
    else
    {
      dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_ALL_RX_ERR | SYS_STATUS_ALL_RX_TO);
      dwt_rxreset();
    }
  }
}

static void app_gateway_a0_loop(void)
{
  uint32_t status = 0;
  uint32_t last_heartbeat = HAL_GetTick();
  uint32_t poll_count = 0;
  uint32_t report4_count = 0;
  uint32_t rx_error_count = 0;
  uint32_t rx_good_count = 0;
  uint32_t unknown_count = 0;
  uint32_t last_debug = HAL_GetTick();
  uint32_t last_unknown_log = 0;

  uart_log("[A0] Gateway anchor active\r\n");
  uart_log("[A0] CSV: RANGE4D,seq,d0_cm,d1_cm,d2_cm,d3_cm,status_hex,pc_ms,rxpwr0_cdbm,fppwr0_cdbm,gap0_cdb,fpidx0_q6,rxpacc0,...\r\n");

  while (1)
  {
    if ((HAL_GetTick() - last_heartbeat) >= 500)
    {
      last_heartbeat = HAL_GetTick();
      HAL_GPIO_TogglePin(LED2_GPIO_Port, LED2_Pin);
    }

    if (A0_VERBOSE_LOG && (HAL_GetTick() - last_debug) >= 3000)
    {
      last_debug = HAL_GetTick();
      uart_printf("[A0] alive rxgood=%lu polls=%lu report4=%lu unknown=%lu rxerr=%lu irq=%lu\r\n",
                  (unsigned long)rx_good_count,
                  (unsigned long)poll_count,
                  (unsigned long)report4_count,
                  (unsigned long)unknown_count,
                  (unsigned long)rx_error_count,
                  (unsigned long)dw_irq_count);
    }

    dwt_rxenable(DWT_START_RX_IMMEDIATE);

    if (wait_for_status(SYS_STATUS_RXFCG, SYS_STATUS_ALL_RX_ERR, 1000, &status))
    {
      uint32_t frame_len;
      uint8_t frame_type;
      uint8_t target_id;

      dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_RXFCG);
      frame_len = dwt_read32bitreg(RX_FINFO_ID) & RX_FINFO_RXFL_MASK_1023;
      memset(rx_buffer, 0, sizeof(rx_buffer));
      if (frame_len <= RX_BUF_LEN)
      {
        dwt_readrxdata(rx_buffer, frame_len, 0);
      }

      uint8_t received_seq = rx_buffer[ALL_MSG_SN_IDX];
      frame_type = rx_buffer[9];
      target_id = rx_buffer[POLL_MSG_TARGET_ID_IDX];
      rx_good_count++;
      rx_buffer[ALL_MSG_SN_IDX] = 0;
      if (memcmp(rx_buffer, rx_poll_msg, ALL_MSG_COMMON_LEN) == 0 &&
          rx_buffer[POLL_MSG_TARGET_ID_IDX] == 0)
      {
        uint64_t poll_rx_ts;
        uint64_t resp_tx_ts;
        uint32_t resp_tx_time;
        int ret;

        poll_rx_ts = get_rx_timestamp_u64();
        resp_tx_time = (uint32_t)((poll_rx_ts + (POLL_RX_TO_RESP_TX_DLY_UUS * UUS_TO_DWT_TIME)) >> 8);
        dwt_setdelayedtrxtime(resp_tx_time);

        resp_tx_ts = (((uint64_t)(resp_tx_time & 0xFFFFFFFEUL)) << 8) + TX_ANT_DLY;
        resp_msg_set_ts(&tx_resp_msg[RESP_MSG_POLL_RX_TS_IDX], poll_rx_ts);
        resp_msg_set_ts(&tx_resp_msg[RESP_MSG_RESP_TX_TS_IDX], resp_tx_ts);

        tx_resp_msg[ALL_MSG_SN_IDX] = frame_seq_nb;
        dwt_writetxdata(sizeof(tx_resp_msg), tx_resp_msg, 0);
        dwt_writetxfctrl(sizeof(tx_resp_msg), 0, 1);
        ret = dwt_starttx(DWT_START_TX_DELAYED);

        if (ret == DWT_SUCCESS && wait_for_status(SYS_STATUS_TXFRS, SYS_STATUS_ALL_RX_ERR, 50, &status))
        {
          dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_TXFRS);
          frame_seq_nb++;
          poll_count++;
          HAL_GPIO_TogglePin(LED1_GPIO_Port, LED1_Pin);
        }
        else
        {
          uart_printf("[A0] RESP_TX_FAIL ret=%d status=0x%08lX\r\n",
                      ret,
                      (unsigned long)status);
          dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_TXFRS | SYS_STATUS_ALL_RX_ERR);
        }
      }
      else if (frame_len >= sizeof(rx_report_msg) &&
               memcmp(rx_buffer, rx_report_msg, ALL_MSG_COMMON_LEN) == 0)
      {
        int32_t corrected_cm = msg_get_i32(&rx_buffer[REPORT_MSG_CORR_CM_IDX]);
        int32_t raw_cm = msg_get_i32(&rx_buffer[REPORT_MSG_RAW_CM_IDX]);
        int32_t report_status = msg_get_i32(&rx_buffer[REPORT_MSG_STATUS_IDX]);

        uart_printf("RELAY,%u,%ld,%ld,0x%08lX,%lu\r\n",
                    received_seq,
                    (long)corrected_cm,
                    (long)raw_cm,
                    (unsigned long)report_status,
                    (unsigned long)HAL_GetTick());
        HAL_GPIO_TogglePin(LED1_GPIO_Port, LED1_Pin);
      }
      else if (frame_len >= sizeof(rx_report4_msg) &&
               memcmp(rx_buffer, rx_report4_msg, ALL_MSG_COMMON_LEN) == 0)
      {
        int32_t d0_cm = msg_get_i32(&rx_buffer[REPORT4_MSG_DIST0_IDX]);
        int32_t d1_cm = msg_get_i32(&rx_buffer[REPORT4_MSG_DIST1_IDX]);
        int32_t d2_cm = msg_get_i32(&rx_buffer[REPORT4_MSG_DIST2_IDX]);
        int32_t d3_cm = msg_get_i32(&rx_buffer[REPORT4_MSG_DIST3_IDX]);
        int32_t report_status = msg_get_i32(&rx_buffer[REPORT4_MSG_STATUS_IDX]);
        range_diag_t diag0 = report4_get_diag(0);
        range_diag_t diag1 = report4_get_diag(1);
        range_diag_t diag2 = report4_get_diag(2);
        range_diag_t diag3 = report4_get_diag(3);

        report4_count++;
        uart_printf("RANGE4D,%u,%ld,%ld,%ld,%ld,0x%08lX,%lu,"
                    "%d,%d,%d,%u,%u,%d,%d,%d,%u,%u,"
                    "%d,%d,%d,%u,%u,%d,%d,%d,%u,%u\r\n",
                    received_seq,
                    (long)d0_cm,
                    (long)d1_cm,
                    (long)d2_cm,
                    (long)d3_cm,
                    (unsigned long)report_status,
                    (unsigned long)HAL_GetTick(),
                    diag0.rx_power_cdbm, diag0.fp_power_cdbm, diag0.power_gap_cdb, diag0.fp_index_q6, diag0.rx_pream_count,
                    diag1.rx_power_cdbm, diag1.fp_power_cdbm, diag1.power_gap_cdb, diag1.fp_index_q6, diag1.rx_pream_count,
                    diag2.rx_power_cdbm, diag2.fp_power_cdbm, diag2.power_gap_cdb, diag2.fp_index_q6, diag2.rx_pream_count,
                    diag3.rx_power_cdbm, diag3.fp_power_cdbm, diag3.power_gap_cdb, diag3.fp_index_q6, diag3.rx_pream_count);
        HAL_GPIO_TogglePin(LED1_GPIO_Port, LED1_Pin);
      }
      else
      {
        unknown_count++;
        if (A0_VERBOSE_LOG && (HAL_GetTick() - last_unknown_log) >= 1000)
        {
          last_unknown_log = HAL_GetTick();
          uart_printf("[A0] unknown seq=%u type=0x%02X target=%u len=%lu status=0x%08lX\r\n",
                      received_seq,
                      frame_type,
                      target_id,
                      (unsigned long)frame_len,
                      (unsigned long)status);
        }
      }
    }
    else
    {
      rx_error_count++;
      dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_ALL_RX_ERR | SYS_STATUS_ALL_RX_TO);
      dwt_rxreset();
    }
  }
}

static void app_tag_reporter_loop(void)
{
  uint32_t status = 0;
  int32_t corrected_cm[4] = {0};
  int32_t raw_cm = 0;
  range_diag_t diag[4] = {0};
  uint32_t range_status = 0;
  uint32_t report_status = 0;

  dwt_setrxaftertxdelay(POLL_TX_TO_RESP_RX_DLY_UUS);
  dwt_setrxtimeout(RESP_RX_TIMEOUT_UUS);

  uart_log("[TAG-REPORT] Active: range with A0-A3, then report RANGE4 by UWB\r\n");

  while (1)
  {
    report_status = 0;
    for (uint8_t anchor_id = 0; anchor_id < 4; anchor_id++)
    {
      memset(&diag[anchor_id], 0, sizeof(diag[anchor_id]));
      if (twr_poll_anchor(anchor_id, &corrected_cm[anchor_id], &raw_cm, &range_status, &diag[anchor_id]))
      {
        report_status |= (1UL << anchor_id);
      }
      else
      {
        corrected_cm[anchor_id] = -1;
      }
      if (INTER_ANCHOR_DELAY_MS > 0)
      {
        HAL_Delay(INTER_ANCHOR_DELAY_MS);
      }
    }

    if (report_status != 0)
    {
      if (REPORT_TX_GUARD_MS > 0)
      {
        HAL_Delay(REPORT_TX_GUARD_MS);
      }
      tx_report4_msg[ALL_MSG_SN_IDX] = frame_seq_nb;
      msg_set_i32(&tx_report4_msg[REPORT4_MSG_DIST0_IDX], corrected_cm[0]);
      msg_set_i32(&tx_report4_msg[REPORT4_MSG_DIST1_IDX], corrected_cm[1]);
      msg_set_i32(&tx_report4_msg[REPORT4_MSG_DIST2_IDX], corrected_cm[2]);
      msg_set_i32(&tx_report4_msg[REPORT4_MSG_DIST3_IDX], corrected_cm[3]);
      msg_set_i32(&tx_report4_msg[REPORT4_MSG_STATUS_IDX], (int32_t)report_status);
      for (uint8_t anchor_id = 0; anchor_id < 4; anchor_id++)
      {
        report4_set_diag(anchor_id, &diag[anchor_id]);
      }

      dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_TXFRS | SYS_STATUS_RXFCG | SYS_STATUS_ALL_RX_ERR | SYS_STATUS_ALL_RX_TO);
      dwt_writetxdata(sizeof(tx_report4_msg), tx_report4_msg, 0);
      dwt_writetxfctrl(sizeof(tx_report4_msg), 0, 0);

      if (dwt_starttx(DWT_START_TX_IMMEDIATE) == DWT_SUCCESS &&
          wait_for_status(SYS_STATUS_TXFRS, SYS_STATUS_ALL_RX_ERR, 100, &status))
      {
        dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_TXFRS);
        uart_printf("[TAG-REPORT] SENT4 seq=%u d0=%ld d1=%ld d2=%ld d3=%ld mask=0x%02lX\r\n",
                    frame_seq_nb,
                    (long)corrected_cm[0],
                    (long)corrected_cm[1],
                    (long)corrected_cm[2],
                    (long)corrected_cm[3],
                    (unsigned long)report_status);
        HAL_GPIO_TogglePin(LED1_GPIO_Port, LED1_Pin);
      }
      else
      {
        uart_printf("[TAG-REPORT] REPORT_TX_FAIL seq=%u status=0x%08lX\r\n",
                    frame_seq_nb,
                    (unsigned long)status);
        dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_TXFRS | SYS_STATUS_ALL_RX_ERR);
        HAL_GPIO_TogglePin(LED2_GPIO_Port, LED2_Pin);
      }
    }
    else
    {
      uart_printf("[TAG-REPORT] RANGE4_ALL_FAIL seq=%u status=0x%08lX\r\n",
                  frame_seq_nb,
                  (unsigned long)range_status);
      HAL_GPIO_TogglePin(LED2_GPIO_Port, LED2_Pin);
    }

    frame_seq_nb++;
    HAL_Delay(RNG_DELAY_MS);
  }
}

static int twr_poll_anchor(uint8_t anchor_id, int32_t *corrected_cm, int32_t *raw_cm, uint32_t *range_status, range_diag_t *diag)
{
  uint32_t status = 0;

  tx_poll_msg[ALL_MSG_SN_IDX] = frame_seq_nb;
  tx_poll_msg[POLL_MSG_TARGET_ID_IDX] = anchor_id;
  dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_TXFRS | SYS_STATUS_RXFCG | SYS_STATUS_ALL_RX_ERR | SYS_STATUS_ALL_RX_TO);
  dwt_writetxdata(sizeof(tx_poll_msg), tx_poll_msg, 0);
  dwt_writetxfctrl(sizeof(tx_poll_msg), 0, 1);

  if (dwt_starttx(DWT_START_TX_IMMEDIATE | DWT_RESPONSE_EXPECTED) != DWT_SUCCESS)
  {
    *range_status = 0;
    return 0;
  }

  if (wait_for_status(SYS_STATUS_RXFCG, SYS_STATUS_ALL_RX_TO | SYS_STATUS_ALL_RX_ERR, 20, &status))
  {
    uint32_t frame_len;

    dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_RXFCG);
    frame_len = dwt_read32bitreg(RX_FINFO_ID) & RX_FINFO_RXFL_MASK_1023;
    memset(rx_buffer, 0, sizeof(rx_buffer));
    if (frame_len <= RX_BUF_LEN)
    {
      dwt_readrxdata(rx_buffer, frame_len, 0);
    }

    rx_buffer[ALL_MSG_SN_IDX] = 0;
    if (memcmp(rx_buffer, rx_resp_msg, ALL_MSG_COMMON_LEN) == 0)
    {
      uint32_t poll_tx_ts;
      uint32_t resp_rx_ts;
      uint32_t poll_rx_ts;
      uint32_t resp_tx_ts;
      int32_t rtd_init;
      int32_t rtd_resp;
      double clock_offset_ratio;
      double tof;
      double distance_m;

      poll_tx_ts = dwt_readtxtimestamplo32();
      resp_rx_ts = dwt_readrxtimestamplo32();
      clock_offset_ratio = dwt_readcarrierintegrator() *
                           (FREQ_OFFSET_MULTIPLIER * HERTZ_TO_PPM_MULTIPLIER_CHAN_2 / 1.0e6);

      resp_msg_get_ts(&rx_buffer[RESP_MSG_POLL_RX_TS_IDX], &poll_rx_ts);
      resp_msg_get_ts(&rx_buffer[RESP_MSG_RESP_TX_TS_IDX], &resp_tx_ts);

      rtd_init = (int32_t)(resp_rx_ts - poll_tx_ts);
      rtd_resp = (int32_t)(resp_tx_ts - poll_rx_ts);
      tof = ((rtd_init - rtd_resp * (1.0 - clock_offset_ratio)) / 2.0) * DWT_TIME_UNITS;
      distance_m = tof * SPEED_OF_LIGHT;
      *raw_cm = (int32_t)(distance_m * 100.0);
      *corrected_cm = *raw_cm + RANGE_BIAS_CM;
      if (diag != NULL)
      {
        *diag = read_range_diag();
      }
      *range_status = status;
      return 1;
    }
  }

  *range_status = status;
  dwt_write32bitreg(SYS_STATUS_ID, SYS_STATUS_ALL_RX_TO | SYS_STATUS_ALL_RX_ERR);
  dwt_rxreset();
  return 0;
}

static range_diag_t read_range_diag(void)
{
  dwt_rxdiag_t raw;
  range_diag_t diag = {0};
  double rx_power_dbm = -999.0;
  double fp_power_dbm = -999.0;
  double n2;
  double fp_sum;

  dwt_readdiagnostics(&raw);
  diag.fp_index_q6 = raw.firstPath;
  diag.rx_pream_count = raw.rxPreamCount;

  if (raw.rxPreamCount > 0)
  {
    n2 = (double)raw.rxPreamCount * (double)raw.rxPreamCount;
    if (raw.maxGrowthCIR > 0)
    {
      rx_power_dbm = 10.0 * log10(((double)raw.maxGrowthCIR * 131072.0) / n2) - 121.74;
    }

    fp_sum = ((double)raw.firstPathAmp1 * (double)raw.firstPathAmp1) +
             ((double)raw.firstPathAmp2 * (double)raw.firstPathAmp2) +
             ((double)raw.firstPathAmp3 * (double)raw.firstPathAmp3);
    if (fp_sum > 0.0)
    {
      fp_power_dbm = 10.0 * log10(fp_sum / n2) - 121.74;
    }
  }

  diag.rx_power_cdbm = (int16_t)(rx_power_dbm * 100.0);
  diag.fp_power_cdbm = (int16_t)(fp_power_dbm * 100.0);
  diag.power_gap_cdb = (int16_t)((rx_power_dbm - fp_power_dbm) * 100.0);
  if (diag.power_gap_cdb > 1000)
  {
    diag.flags |= 0x0001; /* likely NLOS / strong multipath, tune threshold with field data. */
  }
  if ((raw.firstPathAmp1 == 0U) || (raw.rxPreamCount == 0U))
  {
    diag.flags |= 0x0002;
  }

  return diag;
}

static void report4_set_diag(uint8_t anchor_id, const range_diag_t *diag)
{
  uint8_t *base = &tx_report4_msg[REPORT4_MSG_DIAG_BASE_IDX + (anchor_id * REPORT4_DIAG_STRIDE)];

  msg_set_i16(&base[DIAG_RXPWR_CDBM_OFFSET], diag->rx_power_cdbm);
  msg_set_i16(&base[DIAG_FPPWR_CDBM_OFFSET], diag->fp_power_cdbm);
  msg_set_i16(&base[DIAG_GAP_CDB_OFFSET], diag->power_gap_cdb);
  msg_set_u16(&base[DIAG_FP_INDEX_OFFSET], diag->fp_index_q6);
  msg_set_u16(&base[DIAG_RX_PACC_OFFSET], diag->rx_pream_count);
  msg_set_u16(&base[DIAG_FLAGS_OFFSET], diag->flags);
}

static range_diag_t report4_get_diag(uint8_t anchor_id)
{
  const uint8_t *base = &rx_buffer[REPORT4_MSG_DIAG_BASE_IDX + (anchor_id * REPORT4_DIAG_STRIDE)];
  range_diag_t diag;

  diag.rx_power_cdbm = msg_get_i16(&base[DIAG_RXPWR_CDBM_OFFSET]);
  diag.fp_power_cdbm = msg_get_i16(&base[DIAG_FPPWR_CDBM_OFFSET]);
  diag.power_gap_cdb = msg_get_i16(&base[DIAG_GAP_CDB_OFFSET]);
  diag.fp_index_q6 = msg_get_u16(&base[DIAG_FP_INDEX_OFFSET]);
  diag.rx_pream_count = msg_get_u16(&base[DIAG_RX_PACC_OFFSET]);
  diag.flags = msg_get_u16(&base[DIAG_FLAGS_OFFSET]);

  return diag;
}

static uint64_t get_rx_timestamp_u64(void)
{
  uint8_t ts_tab[5];
  uint64_t ts = 0;

  dwt_readrxtimestamp(ts_tab);
  for (int i = 4; i >= 0; i--)
  {
    ts <<= 8;
    ts |= ts_tab[i];
  }
  return ts;
}

static void resp_msg_set_ts(uint8_t *ts_field, uint64_t ts)
{
  for (int i = 0; i < RESP_MSG_TS_LEN; i++)
  {
    ts_field[i] = (uint8_t)(ts >> (i * 8));
  }
}

static void resp_msg_get_ts(uint8_t *ts_field, uint32_t *ts)
{
  *ts = 0;
  for (int i = 0; i < RESP_MSG_TS_LEN; i++)
  {
    *ts += ((uint32_t)ts_field[i]) << (i * 8);
  }
}

static void msg_set_i16(uint8_t *field, int16_t value)
{
  uint16_t uvalue = (uint16_t)value;

  field[0] = (uint8_t)uvalue;
  field[1] = (uint8_t)(uvalue >> 8);
}

static int16_t msg_get_i16(const uint8_t *field)
{
  uint16_t value = ((uint16_t)field[0]) |
                   (((uint16_t)field[1]) << 8);

  return (int16_t)value;
}

static void msg_set_u16(uint8_t *field, uint16_t value)
{
  field[0] = (uint8_t)value;
  field[1] = (uint8_t)(value >> 8);
}

static uint16_t msg_get_u16(const uint8_t *field)
{
  return ((uint16_t)field[0]) |
         (((uint16_t)field[1]) << 8);
}

static void msg_set_i32(uint8_t *field, int32_t value)
{
  uint32_t uvalue = (uint32_t)value;

  field[0] = (uint8_t)(uvalue);
  field[1] = (uint8_t)(uvalue >> 8);
  field[2] = (uint8_t)(uvalue >> 16);
  field[3] = (uint8_t)(uvalue >> 24);
}

static int32_t msg_get_i32(const uint8_t *field)
{
  uint32_t value = ((uint32_t)field[0]) |
                   (((uint32_t)field[1]) << 8) |
                   (((uint32_t)field[2]) << 16) |
                   (((uint32_t)field[3]) << 24);

  return (int32_t)value;
}
/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{
  /* MCU Configuration--------------------------------------------------------*/
  HAL_Init();
  SystemClock_Config();

  MX_GPIO_Init();
  MX_SPI1_Init();
  MX_USART1_UART_Init();

  /* USER CODE BEGIN 2 */
  HAL_GPIO_WritePin(LED1_GPIO_Port, LED1_Pin, GPIO_PIN_SET);
  HAL_GPIO_WritePin(LED2_GPIO_Port, LED2_Pin, GPIO_PIN_RESET);
  dw_irq_gpio_init();

  if (dw1000_init_and_configure() != DWT_SUCCESS)
  {
    while (1)
    {
      uart_log("[BU01] HALTED: fix SPI/CS/RST/3V3 then reset board\r\n");
      HAL_GPIO_TogglePin(LED2_GPIO_Port, LED2_Pin);
      HAL_Delay(1000);
    }
  }

  switch (DW_APP_ROLE)
  {
    case DW_ROLE_INITIATOR_TAG:
      app_initiator_loop();
      break;

    case DW_ROLE_RESPONDER_ANCHOR:
      app_responder_loop();
      break;

    case DW_ROLE_GATEWAY_A0:
      app_gateway_a0_loop();
      break;

    case DW_ROLE_TAG_REPORTER:
      app_tag_reporter_loop();
      break;

    case DW_ROLE_SELFTEST:
    default:
      app_selftest_loop();
      break;
  }
  /* USER CODE END 2 */

  while (1)
  {
  }
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

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

  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK |
                                RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
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
    process_deca_irq();
  }
}
/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  __disable_irq();
  while (1)
  {
  }
}

#ifdef USE_FULL_ASSERT
void assert_failed(uint8_t *file, uint32_t line)
{
  UNUSED(file);
  UNUSED(line);
}
#endif
