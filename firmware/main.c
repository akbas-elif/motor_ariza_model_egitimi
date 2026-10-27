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
#include "usb_host.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <stdio.h>
#include <math.h>
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
I2C_HandleTypeDef hi2c1;

I2S_HandleTypeDef hi2s3;

SPI_HandleTypeDef hspi1;

TIM_HandleTypeDef htim2;

UART_HandleTypeDef huart2;

/* USER CODE BEGIN PV */
#define MPU6050_ADDR           (0x68 << 1)
#define MPU6050_WHO_AM_I_REG   0x75
#define MPU6050_PWR_MGMT_1_REG 0x6B
#define MPU6050_ACCEL_OUT_REG  0x3B
#define MPU6050_ACCEL_CFG_REG  0x1C

uint8_t mpu_who_am_i = 0;
uint8_t mpu_wake_value = 0;
uint8_t mpu_ready = 0;
uint8_t accel_buffer[6];

int16_t accel_x_raw = 0;
int16_t accel_y_raw = 0;
int16_t accel_z_raw = 0;

HAL_StatusTypeDef mpu_status = HAL_ERROR;

volatile uint8_t sample_flag = 0;
volatile uint32_t overrun_count = 0;
uint32_t total_samples = 0;
uint32_t sample_count = 0;
uint32_t i2c_error_count = 0;

uint32_t consec_err = 0;
uint32_t i2c_recovery_count = 0;
uint32_t win_discard_count = 0;
uint32_t next_reinit_tick = 0;

#define WIN_N       1024
#define LSB_PER_G   8192.0f      // +-4 g araligi: 8192 LSB/g

int16_t win_x[WIN_N];
int16_t win_y[WIN_N];
int16_t win_z[WIN_N];
uint16_t win_idx = 0;
uint32_t win_seq = 0;
uint32_t ov_start = 0;
uint32_t err_start = 0;

#define VOTE_N 5
/* 3 duzey demo modeli (veri_egitimi_2/train.py, 13 kayit, motor 1A ve 1B, 2026-10-27):
   rms_mag < ESIK1 -> normal, ESIK1..ESIK2 -> orta bozuk (2 karton), >= ESIK2 -> cok bozuk (somun) */
#define RMS_ESIK1_UG 21844     // normal | orta bozuk      (21.8 mg)
#define RMS_ESIK2_UG 119839    // orta bozuk | cok bozuk   (119.8 mg)

uint8_t vote_buf[VOTE_N];
uint8_t vote_count = 0;        // dolu eleman sayisi (en fazla VOTE_N)
uint8_t vote_pos = 0;
int8_t  last_pred = -1;        // son pencerenin ham tahmini, -1: gecersiz pencere
int8_t  motor_state = -1;      // oylanmis durum: -1 belirsiz, 0 normal, 1 orta bozuk, 2 cok bozuk
int32_t last_rms_mag_ug = 0;   // Live Expressions'ta izlemek icin
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_I2C1_Init(void);
static void MX_I2S3_Init(void);
static void MX_SPI1_Init(void);
static void MX_USART2_UART_Init(void);
static void MX_TIM2_Init(void);
void MX_USB_HOST_Process(void);

/* USER CODE BEGIN PFP */
uint8_t classify(int32_t rms_mag_ug);

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/* Durumu LED'de goster: yesil = normal, turuncu = orta bozuk, kirmizi (sabit) = cok bozuk,
   hepsi sonuk = belirsiz. (Yanip sonen kirmizi = sensor yok, ana dongude.) */
static void show_state(void)
{
  HAL_GPIO_WritePin(GPIOD, GPIO_PIN_12, (motor_state == 0) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(GPIOD, GPIO_PIN_13, (motor_state == 1) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(GPIOD, GPIO_PIN_14, (motor_state == 2) ? GPIO_PIN_SET : GPIO_PIN_RESET);
}

static void vote_reset(void)
{
  vote_count = 0;
  vote_pos = 0;
  motor_state = -1;
  show_state();
}

/* Yeni tahmini son VOTE_N tahminle oyla; VOTE_N dolmadan durum belirsiz kalir.
   Siniflar sirali (0 < 1 < 2) oldugu icin son 5 tahminin ORTANCASI alinir (beraberlik olmaz). */
static void vote_add(uint8_t pred)
{
  vote_buf[vote_pos] = pred;
  vote_pos = (vote_pos + 1) % VOTE_N;
  if (vote_count < VOTE_N) vote_count++;

  if (vote_count == VOTE_N)
  {
    uint8_t cnt[3] = {0, 0, 0};
    for (int i = 0; i < VOTE_N; i++)
    {
      if (vote_buf[i] < 3) cnt[vote_buf[i]]++;
    }
    uint8_t need = VOTE_N / 2 + 1;   // ortanca: kucukten sayarken 3. eleman
    uint8_t acc = 0;
    for (int c = 0; c < 3; c++)
    {
      acc += cnt[c];
      if (acc >= need) { motor_state = (int8_t)c; break; }
    }
  }
  show_state();
}

/* I2C hatti takili kalmissa (SDA dusuk) 9 saat darbesi + STOP ile serbest birak */
static void i2c_bus_clear(void)
{
  GPIO_InitTypeDef g = {0};

  HAL_I2C_DeInit(&hi2c1);              // I2C'yi kapat, pinleri serbest birak

  g.Mode  = GPIO_MODE_OUTPUT_OD;
  g.Pull  = GPIO_PULLUP;
  g.Speed = GPIO_SPEED_FREQ_LOW;
  g.Pin   = GPIO_PIN_6 | GPIO_PIN_9;   // PB6 = SCL, PB9 = SDA
  HAL_GPIO_Init(GPIOB, &g);

  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_6 | GPIO_PIN_9, GPIO_PIN_SET);
  HAL_Delay(1);

  for (int i = 0; i < 9; i++)          // 9 saat darbesi
  {
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_6, GPIO_PIN_RESET);
    HAL_Delay(1);
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_6, GPIO_PIN_SET);
    HAL_Delay(1);
  }

  // STOP kosulu: SCL yuksekken SDA asagidan yukari
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_9, GPIO_PIN_RESET);
  HAL_Delay(1);
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_6, GPIO_PIN_SET);
  HAL_Delay(1);
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_9, GPIO_PIN_SET);
  HAL_Delay(1);

  HAL_I2C_Init(&hi2c1);                // I2C'yi yeniden baslat
}

/* Sensoru bul, kimligini dogrula, uyandir. Basarili ise 1 dondurur */
static uint8_t mpu_init(void)
{
  uint8_t id = 0;
  HAL_StatusTypeDef st;

  mpu_who_am_i = 0;

  st = HAL_I2C_IsDeviceReady(&hi2c1, MPU6050_ADDR, 3, 20);
  if (st != HAL_OK) { mpu_status = st; return 0; }

  st = HAL_I2C_Mem_Read(&hi2c1, MPU6050_ADDR, MPU6050_WHO_AM_I_REG,
                        I2C_MEMADD_SIZE_8BIT, &id, 1, 20);
  mpu_who_am_i = id;
  if (st != HAL_OK) { mpu_status = st; return 0; }

  if ((id != 0x68) && (id != 0x70) && (id != 0x72))
  {
    mpu_status = HAL_ERROR;
    return 0;
  }

  st = HAL_I2C_Mem_Write(&hi2c1, MPU6050_ADDR, MPU6050_PWR_MGMT_1_REG,
                         I2C_MEMADD_SIZE_8BIT, &mpu_wake_value, 1, 20);
  mpu_status = st;
  if (st != HAL_OK) return 0;

  uint8_t cfg = 0x08;   // ACCEL_CONFIG: +-4 g (8192 LSB/g)
  st = HAL_I2C_Mem_Write(&hi2c1, MPU6050_ADDR, MPU6050_ACCEL_CFG_REG,
                         I2C_MEMADD_SIZE_8BIT, &cfg, 1, 20);
  mpu_status = st;
  if (st != HAL_OK) return 0;

  HAL_Delay(100);
  return 1;
}

/* Hat bozulursa: hatti temizle, sensoru yeniden baslat, yarim pencereyi at */
static void mpu_recover(void)
{
  i2c_bus_clear();
  mpu_ready = mpu_init();
  if (!mpu_ready) vote_reset();      // sensor yoksa eski durumu gosterme
  i2c_recovery_count++;
  consec_err = 0;
  if (win_idx > 0) win_discard_count++;
  win_idx = 0;
  sample_flag = 0;
  HAL_GPIO_TogglePin(GPIOD, GPIO_PIN_15);   // mavi LED: kurtarma yapildi
}

/* Dolu pencereden ozet cikar ve tek satir olarak UART'tan gonder */
static void process_window(void)
{
  uint32_t ov  = overrun_count - ov_start;
  uint32_t err = i2c_error_count - err_start;

  int32_t sx = 0, sy = 0, sz = 0;
  for (int i = 0; i < WIN_N; i++)
  {
    sx += win_x[i];
    sy += win_y[i];
    sz += win_z[i];
  }
  float mx = (float)sx / WIN_N;
  float my = (float)sy / WIN_N;
  float mz = (float)sz / WIN_N;

  float qx = 0.0f, qy = 0.0f, qz = 0.0f, peak2 = 0.0f;
  for (int i = 0; i < WIN_N; i++)
  {
    float dx = (float)win_x[i] - mx;
    float dy = (float)win_y[i] - my;
    float dz = (float)win_z[i] - mz;
    qx += dx * dx;
    qy += dy * dy;
    qz += dz * dz;
    float m2 = dx * dx + dy * dy + dz * dz;
    if (m2 > peak2) peak2 = m2;
  }

  float rx = sqrtf(qx / WIN_N);
  float ry = sqrtf(qy / WIN_N);
  float rz = sqrtf(qz / WIN_N);
  float rm = sqrtf((qx + qy + qz) / WIN_N);
  float peak = sqrtf(peak2);
  float crest = (rm > 0.0f) ? (peak / rm) : 0.0f;

  const float k = 1000000.0f / LSB_PER_G;   // ham sayim -> mikro-g (ug)

  int32_t rms_mag_ug = (int32_t)(rm * k);
  last_rms_mag_ug = rms_mag_ug;

  if ((ov == 0) && (err == 0))
  {
    last_pred = (int8_t)classify(rms_mag_ug);
    vote_add((uint8_t)last_pred);
  }
  else
  {
    last_pred = -1;                  // gecersiz pencere oylamaya girmez
  }

  win_seq++;
  char buf[96];
  int len = snprintf(buf, sizeof(buf),
                     "W,%lu,%ld,%ld,%ld,%ld,%ld,%ld,%lu,%lu\r\n",
                     (unsigned long)win_seq,
                     (long)(rx * k), (long)(ry * k), (long)(rz * k),
                     (long)rms_mag_ug, (long)(peak * k),
                     (long)(crest * 1000.0f),
                     (unsigned long)ov, (unsigned long)err);
  HAL_UART_Transmit(&huart2, (uint8_t *)buf, len, 100);

  len = snprintf(buf, sizeof(buf), "C,%lu,%d,%d\r\n",
                 (unsigned long)win_seq, (int)last_pred, (int)motor_state);
  HAL_UART_Transmit(&huart2, (uint8_t *)buf, len, 100);
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
  MX_I2C1_Init();
  MX_I2S3_Init();
  MX_SPI1_Init();
  MX_USB_HOST_Init();
  MX_USART2_UART_Init();
  MX_TIM2_Init();
  /* USER CODE BEGIN 2 */
  i2c_bus_clear();
  mpu_ready = mpu_init();
  next_reinit_tick = HAL_GetTick() + 500;

  HAL_TIM_Base_Start_IT(&htim2);

  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
    while (1)
    {

    /* USER CODE END WHILE */
    MX_USB_HOST_Process();

    /* USER CODE BEGIN 3 */

      if (sample_flag)
      {
        sample_flag = 0;

        if (mpu_ready)
        {
          mpu_status = HAL_I2C_Mem_Read(&hi2c1, MPU6050_ADDR, MPU6050_ACCEL_OUT_REG,
                                        I2C_MEMADD_SIZE_8BIT, accel_buffer, 6, 5);
          if (mpu_status == HAL_OK)
          {
            consec_err = 0;

            accel_x_raw = (int16_t)((accel_buffer[0] << 8) | accel_buffer[1]);
            accel_y_raw = (int16_t)((accel_buffer[2] << 8) | accel_buffer[3]);
            accel_z_raw = (int16_t)((accel_buffer[4] << 8) | accel_buffer[5]);
            total_samples++;

            if (win_idx == 0)
            {
              ov_start = overrun_count;
              err_start = i2c_error_count;
            }
            win_x[win_idx] = accel_x_raw;
            win_y[win_idx] = accel_y_raw;
            win_z[win_idx] = accel_z_raw;
            win_idx++;

            if (win_idx >= WIN_N)
            {
              process_window();
              win_idx = 0;
              sample_flag = 0;
            }
          }
          else
          {
            i2c_error_count++;
            consec_err++;
            if (consec_err >= 3)
            {
              mpu_recover();
            }
          }
        }
        else
        {
          // sensor hazir degil: kirmizi LED, 500 ms'de bir yeniden dene
          sample_count++;
          if (sample_count >= 1000)
          {
            sample_count = 0;
            HAL_GPIO_TogglePin(GPIOD, GPIO_PIN_14);     // kırmızı: sensör yok
          }

          if ((int32_t)(HAL_GetTick() - next_reinit_tick) >= 0)
          {
            mpu_recover();
            next_reinit_tick = HAL_GetTick() + 500;
          }
        }
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

  /** Configure the main internal regulator output voltage
  */
  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLM = 8;
  RCC_OscInitStruct.PLL.PLLN = 336;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = 7;
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
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV4;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV2;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_5) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief I2C1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_I2C1_Init(void)
{

  /* USER CODE BEGIN I2C1_Init 0 */

  /* USER CODE END I2C1_Init 0 */

  /* USER CODE BEGIN I2C1_Init 1 */

  /* USER CODE END I2C1_Init 1 */
  hi2c1.Instance = I2C1;
  hi2c1.Init.ClockSpeed = 400000;
  hi2c1.Init.DutyCycle = I2C_DUTYCYCLE_2;
  hi2c1.Init.OwnAddress1 = 0;
  hi2c1.Init.AddressingMode = I2C_ADDRESSINGMODE_7BIT;
  hi2c1.Init.DualAddressMode = I2C_DUALADDRESS_DISABLE;
  hi2c1.Init.OwnAddress2 = 0;
  hi2c1.Init.GeneralCallMode = I2C_GENERALCALL_DISABLE;
  hi2c1.Init.NoStretchMode = I2C_NOSTRETCH_DISABLE;
  if (HAL_I2C_Init(&hi2c1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN I2C1_Init 2 */

  /* USER CODE END I2C1_Init 2 */

}

/**
  * @brief I2S3 Initialization Function
  * @param None
  * @retval None
  */
static void MX_I2S3_Init(void)
{

  /* USER CODE BEGIN I2S3_Init 0 */

  /* USER CODE END I2S3_Init 0 */

  /* USER CODE BEGIN I2S3_Init 1 */

  /* USER CODE END I2S3_Init 1 */
  hi2s3.Instance = SPI3;
  hi2s3.Init.Mode = I2S_MODE_MASTER_TX;
  hi2s3.Init.Standard = I2S_STANDARD_PHILIPS;
  hi2s3.Init.DataFormat = I2S_DATAFORMAT_16B;
  hi2s3.Init.MCLKOutput = I2S_MCLKOUTPUT_ENABLE;
  hi2s3.Init.AudioFreq = I2S_AUDIOFREQ_96K;
  hi2s3.Init.CPOL = I2S_CPOL_LOW;
  hi2s3.Init.ClockSource = I2S_CLOCK_PLL;
  hi2s3.Init.FullDuplexMode = I2S_FULLDUPLEXMODE_DISABLE;
  if (HAL_I2S_Init(&hi2s3) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN I2S3_Init 2 */

  /* USER CODE END I2S3_Init 2 */

}

/**
  * @brief SPI1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_SPI1_Init(void)
{

  /* USER CODE BEGIN SPI1_Init 0 */

  /* USER CODE END SPI1_Init 0 */

  /* USER CODE BEGIN SPI1_Init 1 */

  /* USER CODE END SPI1_Init 1 */
  /* SPI1 parameter configuration*/
  hspi1.Instance = SPI1;
  hspi1.Init.Mode = SPI_MODE_MASTER;
  hspi1.Init.Direction = SPI_DIRECTION_2LINES;
  hspi1.Init.DataSize = SPI_DATASIZE_8BIT;
  hspi1.Init.CLKPolarity = SPI_POLARITY_LOW;
  hspi1.Init.CLKPhase = SPI_PHASE_1EDGE;
  hspi1.Init.NSS = SPI_NSS_SOFT;
  hspi1.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_2;
  hspi1.Init.FirstBit = SPI_FIRSTBIT_MSB;
  hspi1.Init.TIMode = SPI_TIMODE_DISABLE;
  hspi1.Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
  hspi1.Init.CRCPolynomial = 10;
  if (HAL_SPI_Init(&hspi1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN SPI1_Init 2 */

  /* USER CODE END SPI1_Init 2 */

}

/**
  * @brief TIM2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM2_Init(void)
{

  /* USER CODE BEGIN TIM2_Init 0 */

  /* USER CODE END TIM2_Init 0 */

  TIM_ClockConfigTypeDef sClockSourceConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* USER CODE BEGIN TIM2_Init 1 */

  /* USER CODE END TIM2_Init 1 */
  htim2.Instance = TIM2;
  htim2.Init.Prescaler = 83;
  htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim2.Init.Period = 999;
  htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_Base_Init(&htim2) != HAL_OK)
  {
    Error_Handler();
  }
  sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;
  if (HAL_TIM_ConfigClockSource(&htim2, &sClockSourceConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim2, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM2_Init 2 */

  /* USER CODE END TIM2_Init 2 */

}

/**
  * @brief USART2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_USART2_UART_Init(void)
{

  /* USER CODE BEGIN USART2_Init 0 */

  /* USER CODE END USART2_Init 0 */

  /* USER CODE BEGIN USART2_Init 1 */

  /* USER CODE END USART2_Init 1 */
  huart2.Instance = USART2;
  huart2.Init.BaudRate = 115200;
  huart2.Init.WordLength = UART_WORDLENGTH_8B;
  huart2.Init.StopBits = UART_STOPBITS_1;
  huart2.Init.Parity = UART_PARITY_NONE;
  huart2.Init.Mode = UART_MODE_TX_RX;
  huart2.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart2.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&huart2) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USART2_Init 2 */

  /* USER CODE END USART2_Init 2 */

}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  /* USER CODE BEGIN MX_GPIO_Init_1 */

  /* USER CODE END MX_GPIO_Init_1 */

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOE_CLK_ENABLE();
  __HAL_RCC_GPIOC_CLK_ENABLE();
  __HAL_RCC_GPIOH_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_GPIOD_CLK_ENABLE();

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(CS_I2C_SPI_GPIO_Port, CS_I2C_SPI_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(OTG_FS_PowerSwitchOn_GPIO_Port, OTG_FS_PowerSwitchOn_Pin, GPIO_PIN_SET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOD, GPIO_PIN_12|LD3_Pin|LD5_Pin|LD6_Pin
                          |Audio_RST_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin : CS_I2C_SPI_Pin */
  GPIO_InitStruct.Pin = CS_I2C_SPI_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(CS_I2C_SPI_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : OTG_FS_PowerSwitchOn_Pin */
  GPIO_InitStruct.Pin = OTG_FS_PowerSwitchOn_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(OTG_FS_PowerSwitchOn_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : PDM_OUT_Pin */
  GPIO_InitStruct.Pin = PDM_OUT_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  GPIO_InitStruct.Alternate = GPIO_AF5_SPI2;
  HAL_GPIO_Init(PDM_OUT_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : B1_Pin */
  GPIO_InitStruct.Pin = B1_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_EVT_RISING;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(B1_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : BOOT1_Pin */
  GPIO_InitStruct.Pin = BOOT1_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(BOOT1_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : CLK_IN_Pin */
  GPIO_InitStruct.Pin = CLK_IN_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  GPIO_InitStruct.Alternate = GPIO_AF5_SPI2;
  HAL_GPIO_Init(CLK_IN_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pins : PD12 LD3_Pin LD5_Pin LD6_Pin
                           Audio_RST_Pin */
  GPIO_InitStruct.Pin = GPIO_PIN_12|LD3_Pin|LD5_Pin|LD6_Pin
                          |Audio_RST_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOD, &GPIO_InitStruct);

  /*Configure GPIO pin : OTG_FS_OverCurrent_Pin */
  GPIO_InitStruct.Pin = OTG_FS_OverCurrent_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(OTG_FS_OverCurrent_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : MEMS_INT2_Pin */
  GPIO_InitStruct.Pin = MEMS_INT2_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_EVT_RISING;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(MEMS_INT2_GPIO_Port, &GPIO_InitStruct);

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */
void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
  if (htim->Instance == TIM2)
  {
    if (sample_flag) overrun_count++;
    sample_flag = 1;
  }
}

uint8_t classify(int32_t rms_mag_ug)
{
  if (rms_mag_ug < RMS_ESIK1_UG)
  {
    return 0;  /* normal */
  }
  else if (rms_mag_ug < RMS_ESIK2_UG)
  {
    return 1;  /* orta bozuk */
  }
  else
  {
    return 2;  /* cok bozuk */
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
#ifdef USE_FULL_ASSERT
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
