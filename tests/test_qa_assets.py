import copy
import pytest
from qa_asset_checks import ROOT, inspect_assets
from syllabus import load_config, discover_assets, AssetDiscoveryError


def test_real_qa_assets():
    result=inspect_assets(load_config(ROOT/'config.yaml'))
    assert result['qa_pages'] and result['frame_geometry']


def test_optional_assets_preserve_legacy_discovery(tmp_path):
    cfg=load_config(ROOT/'config.yaml');cfg['paths']['assets']='.'
    for role,pattern in cfg['asset_patterns'].items():
        if role not in cfg['optional_asset_roles']:
            (tmp_path/pattern.replace('*','')).touch()
    found=discover_assets(cfg,tmp_path)
    assert set(found)==set(cfg['asset_patterns'])-set(cfg['optional_asset_roles'])
    for role in cfg['optional_asset_roles']:
        with pytest.raises(AssetDiscoveryError,match=role):
            discover_assets(cfg,tmp_path,roles=[role])
        pattern=cfg['asset_patterns'][role]
        (tmp_path/pattern.replace('*','').swapcase()).touch()
        assert role in discover_assets(cfg,tmp_path,roles=[role])
        (tmp_path/('copy_'+pattern.replace('*',''))).touch()
        with pytest.raises(AssetDiscoveryError,match=role):
            discover_assets(cfg,tmp_path,roles=[role])


def test_unknown_requested_role_is_explicit_error():
    cfg=load_config(ROOT/'config.yaml')
    with pytest.raises(AssetDiscoveryError,match='no configured'):
        discover_assets(cfg,ROOT,roles=['unknown'])


@pytest.mark.parametrize('mutation',['order','placeholder','size','segments'])
def test_invalid_qa_contract_is_rejected(mutation):
    cfg=copy.deepcopy(load_config(ROOT/'config.yaml'))
    if mutation=='order':
        for kind in cfg['qa']['kinds'].values():kind['template_offset']=0
    elif mutation=='placeholder':cfg['qa']['cover']['placeholder']='missing-placeholder'
    elif mutation=='size':cfg['qa']['template_pages']['size'][0]+=1
    else:cfg['qa']['asset_validation']['frame_segments']+=1
    with pytest.raises(AssertionError):inspect_assets(cfg)
