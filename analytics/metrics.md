# Структура базы данных: названия столбцов и описания

---

## 📄 Таблица: `articles` (Метаданные статьи)

| Столбец | Тип | Описание |
|---------|-----|----------|
| `article_id` | UUID/PK | Уникальный идентификатор статьи |
| `doi` | VARCHAR | Digital Object Identifier статьи |
| `title` | TEXT | Полное название статьи |
| `abstract` | TEXT | Аннотация статьи |
| `journal_name` | VARCHAR | Название журнала/издания |
| `publisher` | VARCHAR | Издатель (Elsevier, Springer, MDPI и т.д.) |
| `publication_year` | INTEGER | Год публикации |
| `publication_month` | INTEGER | Месяц публикации (1-12) |
| `publication_day` | INTEGER | День публикации (1-31) |
| `volume` | VARCHAR | Том журнала |
| `issue` | VARCHAR | Номер выпуска |
| `page_start` | INTEGER | Начальная страница |
| `page_end` | INTEGER | Конечная страница |
| `article_type` | ENUM | Тип документа: 'research', 'review', 'patent', 'conference', 'report' |
| `open_access` | BOOLEAN | Доступна ли статья в открытом доступе |
| `language` | VARCHAR | Язык статьи (ISO 639-1) |
| `url` | VARCHAR | Ссылка на полный текст статьи |
| `citations_count` | INTEGER | Количество цитирований (по Crossref/Google Scholar) |
| `impact_factor` | FLOAT | Импакт-фактор журнала на момент публикации |
| `scopus_indexed` | BOOLEAN | Индексируется ли в Scopus |
| `wos_indexed` | BOOLEAN | Индексируется ли в Web of Science |
| `quartile` | VARCHAR | Квартиль журнала (Q1–Q4) |
| `keywords` | TEXT[] | Ключевые слова статьи (массив) |
| `funding_agency` | VARCHAR | Организация-спонсор исследования |
| `country_of_origin` | VARCHAR | Страна, где проведено исследование |

---

## 👥 Таблица: `authors` (Авторы)

| Столбец | Тип | Описание |
|---------|-----|----------|
| `author_id` | UUID/PK | Уникальный ID автора |
| `article_id` | UUID/FK | Ссылка на статью |
| `full_name` | VARCHAR | Полное имя автора |
| `first_name` | VARCHAR | Имя |
| `last_name` | VARCHAR | Фамилия |
| `orcid` | VARCHAR | ORCID идентификатор |
| `affiliation` | VARCHAR | Научное учреждение/университет |
| `department` | VARCHAR | Кафедра/лаборатория |
| `city` | VARCHAR | Город учреждения |
| `country` | VARCHAR | Страна учреждения |
| `email` | VARCHAR | Контактный email (если указан) |
| `is_corresponding` | BOOLEAN | Является ли автором для корреспонденции |

---

## 🔬 Таблица: `alloys` (Сплавы)

| Столбец | Тип | Описание |
|---------|-----|----------|
| `alloy_id` | UUID/PK | Уникальный идентификатор сплава |
| `article_id` | UUID/FK | Ссылка на статью |
| `alloy_name` | VARCHAR | Коммерческое/лабораторное название (Inconel 718, TMW alloy и т.д.) |
| `uns_designation` | VARCHAR | Обозначение по Unified Numbering System (напр. N07718) |
| `astm_standard` | VARCHAR | Стандарт ASTM (если применимо) |
| `iso_standard` | VARCHAR | Стандарт ISO (если применимо) |
| `other_standards` | TEXT[] | Другие стандарты (AMS, EN, JIS и т.д.) |
| `alloy_class` | ENUM | Класс сплава: 'solid_solution', 'gamma_prime_strengthened', 'gamma_double_prime_strengthened', 'oxide_dispersion', 'precipitation_hardened' |
| `application_category` | ENUM[] | Категории применения: ['turbine_blade', 'turbine_disk', 'combustion_chamber', 'heat_exchanger', 'chemical_reactor'] |
| `production_method` | ENUM | Метод производства: 'casting_forging', 'powder_metallurgy', 'additive_manufacturing', 'directional_solidification', 'single_crystal' |
| `form_factor` | ENUM[] | Форма изделия: ['plate', 'sheet', 'tube', 'pipe', 'forging', 'casting', 'wire', 'powder'] |
| `is_single_crystal` | BOOLEAN | Является ли монокристаллическим |
| `is_directionally_solidified` | BOOLEAN | Направленно закристаллизован ли |

---

## ⚗️ Таблица: `chemical_composition` (Химический состав)

| Столбец | Тип | Описание |
|---------|-----|----------|
| `composition_id` | UUID/PK | Уникальный идентификатор записи состава |
| `alloy_id` | UUID/FK | Ссылка на сплав |
| `element_symbol` | VARCHAR | Символ элемента (Ni, Cr, Mo и т.д.) |
| `element_name` | VARCHAR | Полное название элемента |
| `content_min_wt_pct` | FLOAT | Минимальное содержание, мас.% |
| `content_max_wt_pct` | FLOAT | Максимальное содержание, мас.% |
| `content_nominal_wt_pct` | FLOAT | Номинальное/целевое содержание, мас.% |
| `content_min_at_pct` | FLOAT | Минимальное содержание, ат.% |
| `content_max_at_pct` | FLOAT | Максимальное содержание, ат.% |
| `content_nominal_at_pct` | FLOAT | Номинальное содержание, ат.% |
| `is_balance_element` | BOOLEAN | Является ли элементом-балансом (обычно Ni) |
| `is_inevitable_impurity` | BOOLEAN | Является ли неизбежной примесью |
| `measurement_method` | ENUM | Метод измерения: 'nominal', 'icp_oes', 'icp_ms', 'eds', 'wds', 'xrf', 'combustion_analysis' |
| `data_source` | ENUM | Источник данных: 'manufacturer_spec', 'measured_in_study', 'literature_review', 'calculated' |
| `uncertainty_pct` | FLOAT | Погрешность измерения, % |

---

## 🏭 Таблица: `production_parameters` (Параметры производства)

| Столбец | Тип | Описание |
|---------|-----|----------|
| `prod_param_id` | UUID/PK | Уникальный идентификатор |
| `alloy_id` | UUID/FK | Ссылка на сплав |
| `melting_method` | ENUM[] | Методы плавки: ['vacuum_induction_melting', 'electroslag_remelting', 'vacuum_arc_remelting', 'air_melting'] |
| `casting_method` | ENUM | Метод литья: 'investment_casting', 'sand_casting', 'centrifugal_casting', 'continuous_casting' |
| `forging_temp_min_c` | FLOAT | Минимальная температура ковки, °C |
| `forging_temp_max_c` | FLOAT | Максимальная температура ковки, °C |
| `forging_temp_avg_c` | FLOAT | Средняя температура ковки, °C |
| `forging_strain_rate` | FLOAT | Скорость деформации при ковке, с⁻¹ |
| `am_method` | ENUM | Метод аддитивного производства: 'lpbf', 'ebm', 'ded', 'waam', 'binder_jetting' |
| `laser_power_w` | FLOAT | Мощность лазера, Вт |
| `scan_speed_mm_s` | FLOAT | Скорость сканирования, мм/с |
| `hatch_distance_mm` | FLOAT | Расстояние между треками, мм |
| `layer_thickness_mm` | FLOAT | Толщина слоя, мм |
| `beam_diameter_mm` | FLOAT | Диаметр луча, мм |
| `energy_density_linear_j_mm` | FLOAT | Линейная плотность энергии, Дж/мм |
| `energy_density_volumetric_j_mm3` | FLOAT | Объёмная плотность энергии, Дж/мм³ |
| `build_atmosphere` | ENUM | Атмосфера печати: 'argon', 'nitrogen', 'vacuum', 'air' |
| `oxygen_content_ppm` | FLOAT | Содержание кислорода в атмосфере, ppm |
| `preheat_temp_c` | FLOAT | Температура предварительного подогрева, °C |
| `cooling_rate_c_s` | FLOAT | Скорость охлаждения, °C/с |
| `hot_isostatic_pressing` | BOOLEAN | Применялось ли ГИП |
| `hip_temp_c` | FLOAT | Температура ГИП, °C |
| `hip_pressure_mpa` | FLOAT | Давление ГИП, МПа |
| `hip_duration_h` | FLOAT | Длительность ГИП, ч |

---

## 🔥 Таблица: `heat_treatment` (Термообработка)

| Столбец | Тип | Описание |
|---------|-----|----------|
| `ht_id` | UUID/PK | Уникальный идентификатор |
| `alloy_id` | UUID/FK | Ссылка на сплав |
| `treatment_type` | ENUM | Тип обработки: 'solution', 'homogenization', 'aging', 'annealing', 'stress_relief', 'precipitation_hardening' |
| `treatment_stage` | INTEGER | Номер этапа (для многоступенчатой обработки) |
| `temperature_c` | FLOAT | Температура обработки, °C |
| `temperature_relative_to_gamma_prime_solvus_pct` | FLOAT | Температура как % от γ'-solvus (напр. 93–99%) |
| `duration_h` | FLOAT | Длительность выдержки, ч |
| `duration_min` | FLOAT | Длительность выдержки, мин (альтернатива) |
| `heating_rate_c_min` | FLOAT | Скорость нагрева, °C/мин |
| `cooling_method` | ENUM | Метод охлаждения: 'furnace_cool', 'air_cool', 'oil_quench', 'water_quench', 'gas_quench' |
| `cooling_rate_c_min` | FLOAT | Скорость охлаждения, °C/мин |
| `atmosphere` | ENUM | Атмосфера обработки: 'air', 'argon', 'vacuum', 'hydrogen', 'nitrogen' |
| `gamma_prime_solvus_temp_c` | FLOAT | Температура γ'-solvus для данного сплава, °C |
| `gamma_double_prime_solvus_temp_c` | FLOAT | Температура γ''-solvus, °C |
| `post_ht_cold_work_pct` | FLOAT | Процент холодной деформации после ТО |

---

## 🔬 Таблица: `microstructure` (Микроструктура)

| Столбец | Тип | Описание |
|---------|-----|----------|
| `micro_id` | UUID/PK | Уникальный идентификатор |
| `alloy_id` | UUID/FK | Ссылка на сплав |
| `grain_size_astm` | FLOAT | Номер зерна по ASTM E112 |
| `grain_size_um_avg` | FLOAT | Средний размер зерна, мкм |
| `grain_size_um_min` | FLOAT | Минимальный размер зерна, мкм |
| `grain_size_um_max` | FLOAT | Максимальный размер зерна, мкм |
| `grain_morphology` | ENUM | Морфология зерна: 'equiaxed', 'columnar', 'dendritic', 'single_crystal' |
| `gamma_prime_vol_pct` | FLOAT | Объёмная доля γ'-фазы, % |
| `gamma_prime_size_nm_avg` | FLOAT | Средний размер частиц γ', нм |
| `gamma_prime_morphology` | ENUM | Форма γ': 'spherical', 'cuboidal', 'rafted', 'irregular' |
| `gamma_double_prime_vol_pct` | FLOAT | Объёмная доля γ''-фазы, % |
| `gamma_double_prime_size_nm_avg` | FLOAT | Средний размер частиц γ'', нм |
| `laves_phase_vol_pct` | FLOAT | Объёмная доля Laves-фазы, % |
| `delta_phase_vol_pct` | FLOAT | Объёмная доля δ-фазы, % |
| `tcp_phase_present` | BOOLEAN | Присутствуют ли TCP-фазы (σ, μ, P) |
| `tcp_phase_types` | VARCHAR[] | Типы TCP-фаз: ['sigma', 'mu', 'laves', 'p_phase'] |
| `carbide_types` | VARCHAR[] | Типы карбидов: ['mc', 'm23c6', 'm6c', 'm7c3'] |
| `carbide_location` | ENUM[] | Расположение карбидов: ['grain_boundary', 'intragranular', 'both'] |
| `boride_present` | BOOLEAN | Присутствуют ли бориды |
| `porosity_vol_pct` | FLOAT | Объёмная пористость, % |
| `pore_size_um_avg` | FLOAT | Средний размер пор, мкм |
| `crack_density_mm_mm2` | FLOAT | Плотность трещин, мм/мм² |
| `segregation_index` | FLOAT | Индекс микросегрегации (0–1) |
| `texture_coefficient` | FLOAT | Коэффициент текстурности |
| `misfit_gamma_gamma_prime_pct` | FLOAT | Параметр несоответствия решёток γ/γ', % |
| `measurement_technique` | ENUM[] | Методы анализа: ['sem', 'tem', 'ebsd', 'xrd', 'atom_probe', 'optical_microscopy'] |

---

## ⚙️ Таблица: `test_conditions` (Условия испытаний)

| Столбец | Тип | Описание |
|---------|-----|----------|
| `test_id` | UUID/PK | Уникальный идентификатор |
| `alloy_id` | UUID/FK | Ссылка на сплав |
| `test_type` | ENUM | Тип испытания: 'tensile', 'compression', 'creep', 'fatigue', 'lcf', 'hcf', 'fracture_toughness', 'hardness', 'corrosion', 'oxidation', 'thermal_cycling' |
| `standard_reference` | VARCHAR | Стандарт испытаний (ASTM E8, ISO 6892-1, ASTM G28 и т.д.) |
| `specimen_orientation` | ENUM | Ориентация образца: 'longitudinal', 'transverse', 'short_transverse', '45_degree' |
| `specimen_geometry` | VARCHAR | Геометрия образца (напр. 'round', 'flat', 'notched') |
| `gauge_length_mm` | FLOAT | Расчётная длина, мм |
| `cross_section_area_mm2` | FLOAT | Площадь поперечного сечения, мм² |
| `test_temperature_c` | FLOAT | Температура испытания, °C |
| `test_temperature_k` | FLOAT | Температура испытания, К (для расчётов) |
| `environment` | ENUM | Среда испытания: 'air', 'vacuum', 'argon', 'sea_water', 'acid_solution', 'molten_salt' |
| `environment_details` | TEXT | Детали среды (состав раствора, давление, влажность) |
| `ph_value` | FLOAT | Значение pH (для коррозионных тестов) |
| `applied_stress_mpa` | FLOAT | Приложенное напряжение, МПа |
| `applied_strain_pct` | FLOAT | Приложенная деформация, % |
| `strain_rate_s` | FLOAT | Скорость деформации, с⁻¹ |
| `loading_mode` | ENUM | Режим нагружения: 'stress_controlled', 'strain_controlled', 'displacement_controlled' |
| `stress_ratio_r` | FLOAT | Коэффициент асимметрии цикла (для усталости) |
| `frequency_hz` | FLOAT | Частота циклического нагружения, Гц |
| `waveform` | ENUM | Форма волны: 'sinusoidal', 'triangular', 'square', 'hold_time' |
| `hold_time_s` | FLOAT | Время выдержки в цикле, с |
| `test_duration_h` | FLOAT | Длительность испытания, ч |
| `number_of_cycles` | INTEGER | Количество циклов (для усталости) |

---

## 📊 Таблица: `mechanical_properties` (Механические свойства)

| Столбец | Тип | Описание |
|---------|-----|----------|
| `prop_id` | UUID/PK | Уникальный идентификатор |
| `test_id` | UUID/FK | Ссылка на условия испытания |
| `ultimate_tensile_strength_mpa` | FLOAT | Предел прочности при растяжении, МПа |
| `yield_strength_0_2_mpa` | FLOAT | Предел текучести при 0.2%, МПа |
| `yield_strength_0_1_mpa` | FLOAT | Предел текучести при 0.1%, МПа |
| `proportional_limit_mpa` | FLOAT | Предел пропорциональности, МПа |
| `elongation_pct` | FLOAT | Относительное удлинение при разрыве, % |
| `reduction_of_area_pct` | FLOAT | Относительное сужение, % |
| `elastic_modulus_gpa` | FLOAT | Модуль упругости, ГПа |
| `shear_modulus_gpa` | FLOAT | Модуль сдвига, ГПа |
| `poissons_ratio` | FLOAT | Коэффициент Пуассона |
| `hardness_vickers_hv` | FLOAT | Твёрдость по Виккерсу, HV |
| `hardness_rockwell_hrc` | FLOAT | Твёрдость по Роквеллу, HRC |
| `hardness_brinell_hb` | FLOAT | Твёрдость по Бринеллю, HB |
| `fracture_toughness_kic_mpa_sqrt_m` | FLOAT | Вязкость разрушения, МПа·√м |
| `creep_life_h` | FLOAT | Время до разрушения при ползучести, ч |
| `creep_strain_rate_h` | FLOAT | Скорость ползучести, %/ч |
| `creep_strain_at_rupture_pct` | FLOAT | Деформация при разрушении от ползучести, % |
| `fatigue_limit_mpa` | FLOAT | Предел выносливости, МПа |
| `fatigue_strength_at_n_cycles_mpa` | FLOAT | Усталостная прочность при заданном числе циклов, МПа |
| `fatigue_life_cycles` | INTEGER | Число циклов до разрушения |
| `crack_growth_rate_da_dn_m_cycle` | FLOAT | Скорость роста трещины, м/цикл |
| `impact_energy_j` | FLOAT | Ударная вязкость, Дж |
| `fracture_mode` | ENUM | Тип разрушения: 'ductile', 'brittle', 'intergranular', 'transgranular', 'mixed' |

---

## 🌡️ Таблица: `thermal_properties` (Тепловые свойства)

| Столбец | Тип | Описание |
|---------|-----|----------|
| `thermal_id` | UUID/PK | Уникальный идентификатор |
| `alloy_id` | UUID/FK | Ссылка на сплав |
| `melting_point_solidus_c` | FLOAT | Температура солидуса, °C |
| `melting_point_liquidus_c` | FLOAT | Температура ликвидуса, °C |
| `gamma_prime_solvus_c` | FLOAT | Температура растворения γ'-фазы, °C |
| `gamma_double_prime_solvus_c` | FLOAT | Температура растворения γ''-фазы, °C |
| `thermal_expansion_coeff_20_100c_um_m_k` | FLOAT | КТР в диапазоне 20–100 °C, мкм/(м·К) |
| `thermal_expansion_coeff_20_500c_um_m_k` | FLOAT | КТР в диапазоне 20–500 °C, мкм/(м·К) |
| `thermal_expansion_coeff_20_1000c_um_m_k` | FLOAT | КТР в диапазоне 20–1000 °C, мкм/(м·К) |
| `thermal_conductivity_w_m_k_at_20c` | FLOAT | Теплопроводность при 20 °C, Вт/(м·К) |
| `thermal_conductivity_w_m_k_at_500c` | FLOAT | Теплопроводность при 500 °C, Вт/(м·К) |
| `thermal_conductivity_w_m_k_at_1000c` | FLOAT | Теплопроводность при 1000 °C, Вт/(м·К) |
| `specific_heat_j_kg_k_at_20c` | FLOAT | Удельная теплоёмкость при 20 °C, Дж/(кг·К) |
| `specific_heat_j_kg_k_at_500c` | FLOAT | Удельная теплоёмкость при 500 °C, Дж/(кг·К) |
| `density_g_cm3_at_20c` | FLOAT | Плотность при 20 °C, г/см³ |
| `density_g_cm3_at_500c` | FLOAT | Плотность при 500 °C, г/см³ |
| `electrical_resistivity_microhm_cm_at_20c` | FLOAT | Удельное электросопротивление при 20 °C, мкОм·см |

---

## 🧪 Таблица: `corrosion_properties` (Коррозионные свойства)

| Столбец | Тип | Описание |
|---------|-----|----------|
| `corr_id` | UUID/PK | Уникальный идентификатор |
| `alloy_id` | UUID/FK | Ссылка на сплав |
| `corrosion_type` | ENUM | Тип коррозии: 'general', 'pitting', 'crevice', 'intergranular', 'stress_corrosion_cracking', 'oxidation', 'sulfidation', 'chloridation', 'carburization' |
| `test_medium` | VARCHAR | Коррозионная среда (напр. '3.5% NaCl', 'H2SO4 10%', 'molten NaCl-KCl') |
| `temperature_c` | FLOAT | Температура теста, °C |
| `duration_h` | FLOAT | Длительность теста, ч |
| `corrosion_rate_mm_year` | FLOAT | Скорость коррозии, мм/год |
| `corrosion_rate_mpy` | FLOAT | Скорость коррозии, mils per year |
| `mass_loss_mg_cm2` | FLOAT | Потеря массы, мг/см² |
| `corrosion_potential_v_sce` | FLOAT | Коррозионный потенциал относительно н.х.э., В |
| `corrosion_current_density_uA_cm2` | FLOAT | Плотность тока коррозии, мкА/см² |
| `pitting_potential_v_sce` | FLOAT | Потенциал питтингообразования, В |
| `repassivation_potential_v_sce` | FLOAT | Потенциал репассивации, В |
| `critical_pitting_temperature_c` | FLOAT | Критическая температура питтингообразования, °C |
| `critical_crevice_temperature_c` | FLOAT | Критическая температура щелевой коррозии, °C |
| `time_to_scc_failure_h` | FLOAT | Время до разрушения от КРН, ч |
| `oxidation_mass_gain_mg_cm2` | FLOAT | Прирост массы при окислении, мг/см² |
| `scale_thickness_um` | FLOAT | Толщина оксидной плёнки, мкм |
| `scale_adhesion` | ENUM | Адгезия окалины: 'excellent', 'good', 'fair', 'poor', 'spalling' |
| `intergranular_attack_depth_um` | FLOAT | Глубина межкристаллитной коррозии, мкм |
| `astm_g28_practice` | ENUM | Методика ASTM G28: 'Practice_A', 'Practice_B', 'not_applicable' |
| `huey_test_mass_loss_mm_year` | FLOAT | Потеря массы по тесту Huey, мм/год |

---

## 🎯 Таблица: `data_quality` (Качество данных)

| Столбец | Тип | Описание |
|---------|-----|----------|
| `quality_id` | UUID/PK | Уникальный идентификатор |
| `record_id` | UUID | ID записи в любой из таблиц свойств |
| `record_table` | VARCHAR | Название таблицы источника |
| `confidence_level` | ENUM | Уровень доверия: 'high', 'medium', 'low', 'estimated' |
| `data_source_type` | ENUM | Тип источника: 'direct_measurement', 'manufacturer_data', 'literature_value', 'calculated', 'extrapolated' |
| `uncertainty_absolute` | FLOAT | Абсолютная погрешность значения |
| `uncertainty_relative_pct` | FLOAT | Относительная погрешность, % |
| `reproducibility_notes` | TEXT | Примечания о воспроизводимости |
| `outlier_flag` | BOOLEAN | Помечено ли значение как выброс |
| `validation_status` | ENUM | Статус валидации: 'validated', 'pending', 'rejected' |
| `validator_id` | UUID | ID валидатора (если применимо) |
| `last_updated` | TIMESTAMP | Дата последнего обновления записи |

---

## 🔗 Таблица: `alloy_property_links` (Связи)

| Столбец | Тип | Описание |
|---------|-----|----------|
| `link_id` | UUID/PK | Уникальный идентификатор связи |
| `alloy_id` | UUID/FK | Ссылка на сплав |
| `micro_id` | UUID/FK | Ссылка на микроструктуру |
| `ht_id` | UUID/FK | Ссылка на термообработку |
| `test_id` | UUID/FK | Ссылка на условия испытания |
| `prop_id` | UUID/FK | Ссылка на измеренные свойства |
| `is_primary_dataset` | BOOLEAN | Является ли эта комбинация основным набором данных для статьи |

---

## 💡 Рекомендации по использованию

1. **Для ML-модели**: Основные фичи — `chemical_composition`, `production_parameters`, `heat_treatment`, `microstructure`. Целевые переменные — `mechanical_properties`, `corrosion_properties`.

2. **Для анализа корреляций**: Используйте `test_conditions` как контрольные переменные при сравнении свойств.

3. **Для обработки пропусков**: Столбцы `data_quality.confidence_level` и `uncertainty_*` позволяют взвешивать данные при обучении.

4. **Масштабируемость**: Все таблицы используют UUID и внешние ключи для поддержки распределённой архитектуры.

5. **Индексация**: Рекомендуется создать индексы по `alloy_id`, `article_id`, `test_temperature_c`, `element_symbol` для ускорения запросов.