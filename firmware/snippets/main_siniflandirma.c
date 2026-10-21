/* =====================================================================
 * main.c icin siniflandirma eklentisi: classify() + son 5 tahmin cogunluk oylamasi + LED + UART
 * Hedef dosya: C:\Users\Lenovo\Documents\stm_project\led_blink\Core\Src\main.c
 *
 * Her bolumun basinda hangi USER CODE bloguna gidecegi yazili. Blok disina yazma,
 * CubeMX "Generate Code" blok disini siler.
 *
 * Davranis:
 *  - Yalnizca gecerli pencereler (overrun = 0 ve i2c_err = 0) siniflandirilir; egitimde de
 *    yalnizca gecerli == 1 pencereler kullanildi. Gecersiz pencere oylamaya girmez.
 *  - 5 gecerli tahmin birikene kadar durum belirsiz: yesil ve turuncu sonuk.
 *  - Sonra son 5 tahminin cogunlugu: yesil (PD12) = normal, turuncu (PD13) = dengesiz, surekli yanar.
 *  - Sensor kaybolursa oylama sifirlanir, iki LED de soner (kirmizi PD14 yanip soner, eskisi gibi).
 *  - Yesil LED artik "her pencerede yanip son" anlamina gelmez, durum gosterir.
 *  - W satiri DEGISMEDI (logger_pencere.py 10 alan bekliyor). Her W satirindan sonra ayri bir
 *    C satiri gelir:  C,<seq>,<tahmin>,<durum>
 *      tahmin: bu pencerenin ham tahmini (0 normal, 1 dengesiz, -1 gecersiz pencere)
 *      durum : oylanmis durum (0 normal, 1 dengesiz, -1 belirsiz)
 * ===================================================================== */


/* ---------------------------------------------------------------------
 * 1) USER CODE BEGIN PV  -- mevcut degiskenlerin altina EKLE
 * --------------------------------------------------------------------- */
#define VOTE_N 5

uint8_t vote_buf[VOTE_N];
uint8_t vote_count = 0;        // dolu eleman sayisi (en fazla VOTE_N)
uint8_t vote_pos = 0;
int8_t  last_pred = -1;        // son pencerenin ham tahmini, -1: gecersiz pencere
int8_t  motor_state = -1;      // oylanmis durum: -1 belirsiz, 0 normal, 1 dengesiz
int32_t last_rms_mag_ug = 0;   // Live Expressions'ta izlemek icin


/* ---------------------------------------------------------------------
 * 2) USER CODE BEGIN PFP  -- bos blogun icine EKLE
 * --------------------------------------------------------------------- */
uint8_t classify(int32_t rms_mag_ug);


/* ---------------------------------------------------------------------
 * 3) USER CODE BEGIN 0  -- blogun EN BASINA, i2c_bus_clear() fonksiyonunun USTUNE EKLE
 *    (mpu_recover() ve process_window() bunlari kullaniyor, onlardan once tanimli olmali)
 * --------------------------------------------------------------------- */

/* Durumu LED'de goster: yesil = normal, turuncu = dengesiz, ikisi sonuk = belirsiz */
static void show_state(void)
{
  HAL_GPIO_WritePin(GPIOD, GPIO_PIN_12, (motor_state == 0) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_GPIO_WritePin(GPIOD, GPIO_PIN_13, (motor_state == 1) ? GPIO_PIN_SET : GPIO_PIN_RESET);
}

static void vote_reset(void)
{
  vote_count = 0;
  vote_pos = 0;
  motor_state = -1;
  show_state();
}

/* Yeni tahmini son VOTE_N tahminle oyla; VOTE_N dolmadan durum belirsiz kalir */
static void vote_add(uint8_t pred)
{
  vote_buf[vote_pos] = pred;
  vote_pos = (vote_pos + 1) % VOTE_N;
  if (vote_count < VOTE_N) vote_count++;

  if (vote_count == VOTE_N)
  {
    uint8_t ones = 0;
    for (int i = 0; i < VOTE_N; i++) ones += vote_buf[i];
    motor_state = (ones > VOTE_N / 2) ? 1 : 0;
  }
  show_state();
}


/* ---------------------------------------------------------------------
 * 4) USER CODE BEGIN 0 icindeki mpu_recover() -- "mpu_ready = mpu_init();" satirinin ALTINA EKLE
 * --------------------------------------------------------------------- */
  if (!mpu_ready) vote_reset();      // sensor yoksa eski durumu gosterme


/* ---------------------------------------------------------------------
 * 5) USER CODE BEGIN 0 icindeki process_window() -- sonu DEGISTIR
 *
 *    Su satirdan baslayip fonksiyonun kapanis } isaretine kadar olan kismi:
 *        win_seq++;
 *        char buf[96];
 *        ...
 *        HAL_UART_Transmit(&huart2, (uint8_t *)buf, len, 100);
 *    asagidakiyle DEGISTIR. W satiri ayni kaldi; tek fark rms_mag artik
 *    rms_mag_ug degiskeninden yaziliyor, boylece classify() ile ayni deger gidiyor.
 * --------------------------------------------------------------------- */
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


/* ---------------------------------------------------------------------
 * 6) USER CODE BEGIN 3  -- su satiri SIL (yesil LED artik durum gosteriyor):
 *        HAL_GPIO_TogglePin(GPIOD, GPIO_PIN_12);   // yeşil: her pencerede
 * --------------------------------------------------------------------- */


/* ---------------------------------------------------------------------
 * 7) USER CODE BEGIN 4  -- HAL_TIM_PeriodElapsedCallback'in ALTINA EKLE
 *    firmware/snippets/classify.c dosyasindaki fonksiyonu oldugu gibi kopyala
 *    (export_c.py ile uretildi, esik 838154 ug):
 * --------------------------------------------------------------------- */
uint8_t classify(int32_t rms_mag_ug)
{
  if (rms_mag_ug <= 838154)
  {
    return 0;  /* normal */
  }
  else
  {
    return 1;  /* dengesiz */
  }
}
