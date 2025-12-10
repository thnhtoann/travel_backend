"""
Image Search Service - Free Version using DuckDuckGo
===================================================

Service tìm kiếm ảnh miễn phí sử dụng duckduckgo_search.
Không cần API key, hoàn toàn miễn phí.
Có retry logic và rate limiting để tránh bị chặn.
"""
from typing import List, Optional, Dict
import logging
import time
import random

logger = logging.getLogger(__name__)

# DuckDuckGo Search
# Thử cả 2 package: ddgs (mới) và duckduckgo_search (cũ)
DDGS_AVAILABLE = False
DDGS = None
try:
    from ddgs import DDGS
    DDGS_AVAILABLE = True
    logger.info("Using ddgs package (new)")
except ImportError:
    try:
        from duckduckgo_search import DDGS
        DDGS_AVAILABLE = True
        logger.info("Using duckduckgo_search package (old)")
    except ImportError:
        DDGS_AVAILABLE = False
        logger.warning("Neither ddgs nor duckduckgo_search installed. Install with: pip install ddgs")


class ImageSearchService:
    """
    Service tìm kiếm ảnh miễn phí sử dụng DuckDuckGo Search.
    
    Không cần API key, hoàn toàn miễn phí.
    Có rate limiting protection để tránh bị chặn IP.
    """
    
    def __init__(self):
        if not DDGS_AVAILABLE:
            raise ImportError(
                "Neither ddgs nor duckduckgo_search is installed. "
                "Install with: pip install ddgs"
            )
        # Không tạo instance ở đây, sẽ tạo mới cho mỗi request
    
    def find_images(
        self,
        query: str,
        limit: int = 5,
        min_width: Optional[int] = None,
        min_height: Optional[int] = None,
        max_retries: int = 3
    ) -> List[Dict[str, str]]:
        """
        Tìm kiếm ảnh từ DuckDuckGo với retry logic và rate limiting.
        
        Args:
            query: Từ khóa tìm kiếm (ví dụ: "Hồ Gươm")
            limit: Số lượng ảnh tối đa cần lấy
            min_width: Chiều rộng tối thiểu (optional)
            min_height: Chiều cao tối thiểu (optional)
            max_retries: Số lần retry tối đa khi gặp lỗi
            
        Returns:
            List[Dict] chứa các ảnh với format:
            [
                {
                    "url": "https://...",
                    "title": "...",
                    "image": "https://...",
                    "thumbnail": "https://...",
                    "width": 1920,
                    "height": 1080
                },
                ...
            ]
        """
        if not DDGS_AVAILABLE:
            logger.error("DuckDuckGo Search is not available")
            return []
        
        # Tạo query với context Vietnam travel
        search_query = f"{query} vietnam travel scenery"
        
        # Retry logic
        for attempt in range(max_retries):
            try:
                # Rate limiting: Random delay 2-5 giây trước mỗi request
                if attempt > 0:
                    wait_time = random.uniform(2, 5)
                    logger.info(f"Retry attempt {attempt + 1}/{max_retries}, waiting {wait_time:.1f}s...")
                    time.sleep(wait_time)
                else:
                    # Delay ngẫu nhiên cho request đầu tiên
                    time.sleep(random.uniform(2, 5))
                
                logger.info(f"Searching images for query: {search_query} (attempt {attempt + 1}/{max_retries})")
                
                # Tạo DDGS instance mới cho mỗi request (tránh stale connection)
                ddgs = DDGS()
                
                # Gọi DuckDuckGo Search API
                # DDGS.images() cần positional argument 'query' thay vì 'keywords'
                results = list(
                    ddgs.images(
                        query=search_query,
                        max_results=limit * 2  # Lấy nhiều hơn để filter
                    )
                )
                
                if not results:
                    logger.warning(f"No images found for query: {query}")
                    return []
                
                # Filter và format kết quả
                filtered_results = []
                for result in results:
                    try:
                        # Lấy thông tin từ result
                        image_url = result.get("image") or result.get("url", "")
                        if not image_url:
                            continue
                        
                        # Validate URL: Phải bắt đầu bằng http/https
                        if not (image_url.startswith("http://") or image_url.startswith("https://")):
                            logger.debug(f"Skipping invalid URL: {image_url[:50]}...")
                            continue
                        
                        # Filter theo kích thước nếu có yêu cầu
                        width = result.get("width", 0)
                        height = result.get("height", 0)
                        
                        if min_width and width < min_width:
                            continue
                        if min_height and height < min_height:
                            continue
                        
                        # Format result
                        formatted_result = {
                            "url": image_url,
                            "title": result.get("title", query),
                            "image": image_url,
                            "thumbnail": result.get("thumbnail", image_url),
                            "width": width,
                            "height": height
                        }
                        
                        filtered_results.append(formatted_result)
                        
                        # Đủ số lượng cần thiết
                        if len(filtered_results) >= limit:
                            break
                            
                    except Exception as e:
                        logger.warning(f"Error processing image result: {e}")
                        continue
                
                logger.info(f"Found {len(filtered_results)} valid images for query: {query}")
                return filtered_results
                
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"Error searching images (attempt {attempt + 1}/{max_retries}): {error_msg}")
                
                # Nếu là rate limit (403) hoặc lỗi tương tự, chờ lâu hơn
                if "403" in error_msg or "rate limit" in error_msg.lower() or "forbidden" in error_msg.lower():
                    if attempt < max_retries - 1:
                        wait_time = 10  # Chờ 10 giây trước khi retry
                        logger.warning(f"Rate limit detected, waiting {wait_time}s before retry...")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"Rate limit exceeded after {max_retries} attempts")
                        return []
                else:
                    # Lỗi khác, retry ngay
                    if attempt < max_retries - 1:
                        continue
                    else:
                        logger.error(f"Error searching images with DuckDuckGo after {max_retries} attempts: {e}", exc_info=True)
                        return []
        
        # Nếu đến đây nghĩa là đã hết retries
        logger.error(f"Failed to search images after {max_retries} attempts")
        return []
    
    def find_images_for_destination(
        self,
        destination_name: str,
        city_name: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, str]]:
        """
        Tìm kiếm ảnh cho một địa điểm du lịch cụ thể.
        
        Args:
            destination_name: Tên địa điểm (ví dụ: "Hồ Gươm")
            city_name: Tên thành phố (ví dụ: "Hà Nội", optional)
            limit: Số lượng ảnh tối đa
            
        Returns:
            List[Dict] chứa các ảnh
        """
        # Tạo query với context
        if city_name:
            query = f"{destination_name} {city_name}"
        else:
            query = destination_name
        
        return self.find_images(query, limit=limit, min_width=400, min_height=300)

