"""Regressoes do calendario de cobranca de NFs SETTA."""
import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from nf_launch_deadline import (
    eh_dia_util, inicio_valido_envio, prazo_lancamento, dias_atraso_uteis
)

TZ = ZoneInfo("America/Sao_Paulo")


class TestFeriadosNFS(unittest.TestCase):
    def test_feriado_nacional_semana(self):
        self.assertFalse(eh_dia_util(date(2026, 11, 20)))
        self.assertTrue(eh_dia_util(date(2026, 11, 19)))
        self.assertTrue(eh_dia_util(date(2026, 11, 23)))

    def test_datas_moveis_2027(self):
        self.assertFalse(eh_dia_util(date(2027, 3, 26)))  # Sexta-feira Santa
        self.assertFalse(eh_dia_util(date(2027, 5, 27)))  # Corpus Christi

    def test_feriados_municipais(self):
        self.assertFalse(eh_dia_util(date(2027, 5, 24)))  # aniversario Patos
        self.assertFalse(eh_dia_util(date(2027, 6, 13)))  # Santo Antonio
        self.assertFalse(eh_dia_util(date(2027, 8, 15)))  # Assuncao

    def test_ponto_facultativo_nao_e_feriado(self):
        self.assertTrue(eh_dia_util(date(2027, 2, 9)))  # Carnaval

    def test_prazo_cruza_consciencia_negra_e_fim_semana(self):
        enviado = datetime(2026, 11, 19, 17, 0, tzinfo=TZ)
        self.assertEqual(prazo_lancamento(enviado), datetime(2026, 11, 23, 17, 0, tzinfo=TZ))

    def test_inicio_no_feriado(self):
        enviado = datetime(2026, 11, 20, 10, 0, tzinfo=TZ)
        self.assertEqual(inicio_valido_envio(enviado), datetime(2026, 11, 23, 7, 0, tzinfo=TZ))
        self.assertEqual(prazo_lancamento(enviado), datetime(2026, 11, 24, 7, 0, tzinfo=TZ))

    def test_prazo_cruza_natal(self):
        enviado = datetime(2026, 12, 24, 17, 0, tzinfo=TZ)
        self.assertEqual(prazo_lancamento(enviado), datetime(2026, 12, 28, 17, 0, tzinfo=TZ))

    def test_atraso_congela_feriado_e_fim_semana(self):
        vencimento = datetime(2026, 11, 19, 17, 0, tzinfo=TZ)
        self.assertEqual(dias_atraso_uteis(vencimento, datetime(2026, 11, 23, 10, 0, tzinfo=TZ)), 1)
        self.assertEqual(dias_atraso_uteis(vencimento, datetime(2026, 11, 24, 10, 0, tzinfo=TZ)), 2)

    def test_dia_comum_preservado(self):
        enviado = datetime(2026, 11, 23, 10, 0, tzinfo=TZ)
        self.assertEqual(prazo_lancamento(enviado), datetime(2026, 11, 24, 10, 0, tzinfo=TZ))


if __name__ == "__main__":
    unittest.main()
