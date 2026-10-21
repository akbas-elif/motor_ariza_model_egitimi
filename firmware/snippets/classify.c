/* OTOMATIK URETILDI: tools/export_c.py -- elle degistirme;
 * kurali degistirmek icin train.py ve export_c.py'yi yeniden calistir.
 * Kaynak: models/final_tree.joblib (gercek olcum verisi, normal / dengesiz)
 * Birim: rms_mag_ug = mikro-g, pencere ortalamasi cikarilmis bileske RMS
 * Donus: 0 = normal, 1 = dengesiz
 * Dogrulama: 235 pencerede sklearn ile fark 0, etikete gore hata 0
 *
 * main.c'ye yerlesim:
 *   USER CODE BEGIN PFP : uint8_t classify(int32_t rms_mag_ug);
 *   USER CODE BEGIN 4   : asagidaki fonksiyon
 */
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
