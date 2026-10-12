import json
import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import Customer, Order, Wallet, WalletTransaction


class WalletPaymentFlowTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(
            name='مشتری آزمایشی',
            phone='09123456789',
        )
        self.wallet = Wallet.objects.create(
            customer=self.customer,
            balance=Decimal('0'),
        )
        self.order = Order.objects.create(
            customer=self.customer,
            total_price=Decimal('25000'),
        )
        User = get_user_model()
        self.staff = User.objects.create_user(
            username='wallet-admin',
            password='test-password',
            is_staff=True,
            is_superuser=True,
        )

    def customer_client(self):
        client = Client()
        session = client.session
        session['customer_id'] = self.customer.id
        session['customer_logged_in'] = True
        session.save()
        return client

    def test_successful_wallet_payment_returns_to_the_same_invoice(self):
        self.wallet.balance = Decimal('60000')
        self.wallet.save()

        response = self.customer_client().get(
            reverse('wallet_pay_order', args=[self.order.id])
        )

        self.assertEqual(
            response['Location'],
            f"/?order_id={self.order.id}#track-section",
        )
        self.order.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertTrue(self.order.is_paid)
        self.assertEqual(self.wallet.balance, Decimal('35000'))
        self.assertTrue(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                order=self.order,
                transaction_type='debit',
                amount=Decimal('25000'),
            ).exists()
        )

    def test_insufficient_wallet_balance_still_returns_to_the_invoice(self):
        self.wallet.balance = Decimal('10000')
        self.wallet.save()

        response = self.customer_client().get(
            reverse('wallet_pay_order', args=[self.order.id])
        )

        self.assertEqual(
            response['Location'],
            f"/?order_id={self.order.id}#track-section",
        )
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_paid)

    def test_admin_manual_top_up_accepts_persian_grouped_amount_and_can_pay_invoice(self):
        admin_client = Client()
        admin_client.force_login(self.staff)
        response = admin_client.post(
            reverse('panel_customer_update', args=[self.customer.id]),
            {
                'name': self.customer.name,
                'phone': self.customer.phone,
                'password': '',
                'wallet_balance': '۱٬۰۰۰٬۰۰۰',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('1000000'))
        self.assertTrue(
            WalletTransaction.objects.filter(
                wallet=self.wallet,
                transaction_type='credit',
                amount=Decimal('1000000'),
                description='شارژ دستی توسط مدیریت',
            ).exists()
        )

        response = self.customer_client().get(
            reverse('wallet_pay_order', args=[self.order.id])
        )
        self.assertEqual(
            response['Location'],
            f"/?order_id={self.order.id}#track-section",
        )
        self.wallet.refresh_from_db()
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_paid)
        self.assertEqual(self.wallet.balance, Decimal('975000'))


def login_customer(client, customer):
    session = client.session
    session['customer_id'] = customer.id
    session['customer_logged_in'] = True
    session.save()
    return client


class ReceiptAccessTests(TestCase):
    def setUp(self):
        self.owner = Customer.objects.create(name='صاحب سفارش', phone='09120000011')
        self.other = Customer.objects.create(name='مشتری دیگر', phone='09120000012')
        self.order = Order.objects.create(customer=self.owner, total_price=Decimal('10000'))
        self.url = reverse('print_receipt', args=[self.order.id])

    def test_guest_is_sent_to_login(self):
        response = Client().get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('customer_login'), response['Location'])
        self.assertNotContains(Client().get(self.url, follow=True), self.owner.phone)

    def test_other_customer_gets_404(self):
        response = login_customer(Client(), self.other).get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_owner_and_staff_can_view(self):
        response = login_customer(Client(), self.owner).get(self.url)
        self.assertContains(response, self.owner.phone)
        self.assertNotContains(response, f'phone={self.owner.phone}')
        staff = get_user_model().objects.create_user('receipt-staff', password='x', is_staff=True)
        client = Client()
        client.force_login(staff)
        self.assertContains(client.get(self.url), self.owner.name)


class WalletVerifyTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='شارژ کننده', phone='09120000013')
        self.wallet = Wallet.objects.create(customer=self.customer, balance=Decimal('0'))
        self.tx = WalletTransaction.objects.create(
            wallet=self.wallet, transaction_type='credit', amount=Decimal('20000'), authority='A-test-1',
        )
        self.client = login_customer(Client(), self.customer)
        self.url = reverse('verify_wallet') + f'?transaction_id={self.tx.id}&Authority=A-test-1&Status=OK'

    def gateway(self, code=100):
        from unittest import mock
        response = mock.Mock(status_code=200, content=b'1')
        response.json.return_value = {'data': {'code': code, 'ref_id': 12345}}
        return mock.patch('orders.views.requests.post', return_value=response)

    def test_cancelled_payment_adds_nothing(self):
        url = reverse('verify_wallet') + f'?transaction_id={self.tx.id}&Authority=A-test-1&Status=NOK'
        response = self.client.get(url, follow=True)
        self.assertContains(response, 'پرداخت لغو شد')
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 0)

    def test_repeated_callback_credits_once(self):
        with self.gateway(100):
            self.client.get(self.url)
        with self.gateway(101):
            self.client.get(self.url)
            self.client.get(self.url)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('20000'))

    def test_claim_is_single_use(self):
        from .views import credit_wallet_transaction
        self.assertTrue(credit_wallet_transaction(self.tx, '1'))
        self.assertFalse(credit_wallet_transaction(self.tx, '1'))
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal('20000'))

    def test_other_customer_cannot_verify(self):
        other = login_customer(Client(), Customer.objects.create(name='دیگری', phone='09120000014'))
        with self.gateway(100):
            other.get(self.url)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, 0)


class CourierLocationTests(TestCase):
    def test_clean_courier_location(self):
        from .views import clean_courier_location
        ok, error = clean_courier_location('۳۵.۷', '51.3', '۱۲۳۴۵ ۶۷۸۹۰')
        self.assertIsNone(error)
        self.assertEqual(ok, ('35.700000', '51.300000', '1234567890'))
        for lat, lng in [('nan', '51'), ('inf', '51'), ('999', '51'), ('35', '-999'), ('', ''), ('abc', '51')]:
            self.assertIsNotNone(clean_courier_location(lat, lng, '1234567890')[1], (lat, lng))
        for postal in ['123456789', '12345678901', 'abcdefghij', '']:
            self.assertIsNotNone(clean_courier_location('35.7', '51.3', postal)[1], postal)


class DeliveryCourierRequestTests(TestCase):
    def setUp(self):
        self.customer = Customer.objects.create(name='پیک', phone='09120000015')
        self.order = Order.objects.create(customer=self.customer, status='ready', total_price=Decimal('100000'))
        self.client = login_customer(Client(), self.customer)

    def post(self, payload, client=None):
        return (client or self.client).post(reverse('request_courier'), json.dumps(payload), content_type='application/json')

    def test_request_then_edit_until_dispatched(self):
        payload = {'order_id': self.order.id, 'lat': '35.7', 'lng': '51.3', 'postal': '۱۲۳۴۵۶۷۸۹۰'}
        self.assertEqual(self.post(payload).json()['status'], 'success')
        self.order.refresh_from_db()
        self.assertTrue(self.order.delivery_courier_requested)
        self.assertEqual(self.order.delivery_postal_code, '1234567890')
        payload['postal'] = '1111111111'
        self.assertEqual(self.post(payload).json()['message'], 'آدرس ارسال به‌روز شد.')
        self.order.delivery_courier_dispatched = True
        self.order.save()
        self.assertEqual(self.post(payload).status_code, 400)

    def test_errors_are_persian(self):
        other = login_customer(Client(), Customer.objects.create(name='دیگری', phone='09120000016'))
        for response in [
            self.post({'order_id': 'abc', 'lat': '35.7', 'lng': '51.3', 'postal': '1234567890'}),
            self.post({'order_id': self.order.id, 'lat': '35.7', 'lng': '51.3', 'postal': '1234567890'}, other),
            self.post([]),
        ]:
            message = response.json()['message']
            self.assertTrue(re.search('[آ-ی]', message), message)
            self.assertNotIn('matches the given query', message)
        self.order.status = 'delivered'
        self.order.save()
        response = self.post({'order_id': self.order.id, 'lat': '35.7', 'lng': '51.3', 'postal': '1234567890'})
        self.assertEqual(response.json()['message'], 'این سفارش قبلاً تحویل داده شده است.')

    def test_tracking_page_hides_method_chooser_after_request(self):
        page = self.client.get(reverse('home'), {'order_id': self.order.id}).content.decode()
        self.assertIn('نحوه دریافت لباس را انتخاب کنید', page)
        self.post({'order_id': self.order.id, 'lat': '35.7', 'lng': '51.3', 'postal': '1234567890'})
        page = self.client.get(reverse('home'), {'order_id': self.order.id}).content.decode()
        self.assertNotIn('نحوه دریافت لباس را انتخاب کنید', page)
        self.assertIn('ویرایش آدرس ارسال', page)


class PlaceOrderTests(TestCase):
    def setUp(self):
        from .models import PriceCategory, PriceItem
        self.customer = Customer.objects.create(name='سفارش‌دهنده', phone='09120000017')
        men = PriceCategory.objects.create(name='مردانه')
        self.shirt = PriceItem.objects.create(category=men, name='پیراهن', dry_clean_price='220000', iron_only_price='160000')
        self.trousers = PriceItem.objects.create(category=men, name='شلوار', dry_clean_price='220,000', iron_only_price='160000')
        self.coat = PriceItem.objects.create(category=men, name='کاپشن', dry_clean_price='', iron_only_price=None)
        self.client = login_customer(Client(), self.customer)

    def post(self, payload, raw=None):
        body = raw if raw is not None else json.dumps(payload)
        return self.client.post(reverse('place_order'), body, content_type='application/json')

    def test_normal_order_totals_and_labels(self):
        response = self.post({'items': [
            {'line_id': self.shirt.id, 'quantity': 2, 'description': 'یقه لک دارد'},
            {'line_id': self.trousers.id, 'quantity': 1, 'iron_only': True},
        ]})
        data = response.json()
        self.assertEqual(data['status'], 'success')
        order = Order.objects.get(id=data['order_id'])
        self.assertEqual(order.total_price, Decimal('660000'))
        self.assertEqual(data['total'], 660000)
        names = sorted(order.orderitem_set.values_list('item_name', flat=True))
        self.assertEqual(names, ['شلوار مردانه (فقط اتو)', 'پیراهن مردانه (خشکشویی + اتو)'])

    def test_bad_input_never_leaves_an_order(self):
        bad_payloads = [{'items': []}, {'items': 'x'}] + [
            {'items': [{'line_id': self.shirt.id, 'quantity': q}]}
            for q in (0, -5, '1.5', 2.7, 99999, 10 ** 20, 'abc', None, True)
        ]
        bad_payloads += [
            {'items': [{'line_id': 999999, 'quantity': 1}]},
            {'items': [{'line_id': self.coat.id, 'quantity': 1, 'iron_only': True}]},
            {'items': [self.shirt.id]},
            {'items': [{'line_id': self.shirt.id, 'quantity': 1}], 'delivery_method': 'courier', 'lat': 'nan', 'lng': '51', 'postal': '1234567890'},
        ]
        for payload in bad_payloads:
            response = self.post(payload)
            self.assertEqual(response.json()['status'], 'error', payload)
            self.assertTrue(re.search('[آ-ی]', response.json()['message']), payload)
        for raw in ['[]', '{bad', 'null']:
            self.assertEqual(self.post(None, raw=raw).json()['status'], 'error')
        self.assertEqual(Order.objects.count(), 0)

    def test_changed_price_is_rejected(self):
        response = self.post({'items': [{'line_id': self.shirt.id, 'quantity': 1, 'price_numeric': 200000}]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Order.objects.count(), 0)

    def test_unpriced_item_is_allowed_at_zero(self):
        data = self.post({'items': [{'line_id': self.coat.id, 'quantity': 1, 'price_numeric': None}]}).json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['total'], 0)

    def test_courier_order_saves_normalized_location_and_address(self):
        data = self.post({
            'items': [{'line_id': self.shirt.id, 'quantity': 1}], 'delivery_method': 'courier',
            'lat': '35.72', 'lng': '51.29', 'postal': '۱۲۳۴۵۶۷۸۹۰', 'address': 'تهران، پلاک ۱', 'save_address': True,
        }).json()
        order = Order.objects.get(id=data['order_id'])
        self.assertEqual((order.status, order.postal_code), ('collecting', '1234567890'))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.address_postal_code, '1234567890')
        self.assertTrue(self.customer.has_saved_address)

    def test_wallet_payment_on_order(self):
        Wallet.objects.create(customer=self.customer, balance=Decimal('300000'))
        data = self.post({'items': [{'line_id': self.shirt.id, 'quantity': 1}], 'use_wallet': True}).json()
        self.assertTrue(data['paid_by_wallet'])
        self.assertEqual(Wallet.objects.get(customer=self.customer).balance, Decimal('58000'))
        data = self.post({'items': [{'line_id': self.shirt.id, 'quantity': 1}], 'use_wallet': True}).json()
        self.assertTrue(data['wallet_insufficient'])
        self.assertFalse(Order.objects.get(id=data['order_id']).is_paid)
        self.assertEqual(Wallet.objects.get(customer=self.customer).balance, Decimal('58000'))
        self.assertEqual(WalletTransaction.objects.filter(transaction_type='debit').count(), 1)


class HomeMessagesTests(TestCase):
    def test_flash_messages_render_on_home(self):
        customer = Customer.objects.create(name='پیام', phone='09120000018')
        order = Order.objects.create(customer=customer, total_price=Decimal('50000'))
        Wallet.objects.create(customer=customer, balance=Decimal('0'))
        client = login_customer(Client(), customer)
        response = client.get(reverse('wallet_pay_order', args=[order.id]), follow=True)
        self.assertContains(response, 'flash-msg')
        self.assertContains(response, 'موجودی کیف پول کافی نیست')
